"""Execute validated LLM actions."""

from __future__ import annotations

from uuid import uuid4

from src.bot.keyboards import manager_measurement_keyboard
from src.bot.telegram_sender import telegram_sender
from src.bot.whatsapp_sender import manager_whatsapp_sender
from src.db import postgres
from src.engine.fsm import is_valid_transition
from src.engine.measurement_service import schedule_measurement
from src.engine.pricing_cache import pricing_cache
from src.engine.pricing_engine import calculate_price
from src.engine.render_requirements import merge_render_params, missing_render_params
from src.engine.render_engine import render_partition
from src.models import (
    ActionsJson,
    RenderPartitionAction,
    ScheduleMeasurementAction,
    StatePatch,
    UpdateClientProfileAction,
)
from src.utils.json_tools import ensure_json_object
from src.utils.query_parser import normalize_render_params
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_MEASUREMENT_FIELD_MAP = {
    "measurement_date": "дату",
    "measurement_time": "время",
    "measurement_name": "имя",
    "measurement_phone": "телефон",
    "measurement_address": "адрес",
}


def _measurement_state_payload(collected_params: dict) -> dict[str, str]:
    collected = ensure_json_object(collected_params)
    return {
        "date": str(collected.get("measurement_date") or "").strip(),
        "time": str(collected.get("measurement_time") or "").strip(),
        "client_name": str(collected.get("measurement_name") or "").strip(),
        "phone": str(collected.get("measurement_phone") or "").strip(),
        "address": str(collected.get("measurement_address") or "").strip(),
    }


def _missing_measurement_fields(collected_params: dict) -> list[str]:
    collected = ensure_json_object(collected_params)
    missing: list[str] = []
    for key, label in _MEASUREMENT_FIELD_MAP.items():
        if not str(collected.get(key) or "").strip():
            missing.append(label)
    return missing


async def _send_manager_whatsapp_notification(phone: str, text: str, reply_markup: dict | None = None) -> None:
    try:
        await manager_whatsapp_sender.send_message("", phone, text, reply_markup=reply_markup)
    except Exception as exc:
        logger.warning(
            "manager_whatsapp_notify_failed",
            extra={"phone": phone, "error": str(exc)},
        )


def _order_from_rendered_draft(draft: dict | None) -> dict | None:
    if not draft:
        return None
    request_id = draft.get("rendered_order_id") or draft.get("request_id")
    if not request_id:
        return None
    return {
        "request_id": request_id,
        "chat_id": draft.get("chat_id"),
        "status": draft.get("order_status"),
        "details_json": ensure_json_object(draft.get("details_json")),
        "render_paths": ensure_json_object(draft.get("render_paths")),
        "price": ensure_json_object(draft.get("price")),
        "collected_params": ensure_json_object(draft.get("collected_params")),
    }


async def apply_actions(
    actions: ActionsJson,
    chat_id: int,
    client_profile: dict | None,
    conversation_state: dict | None,
    pg_pool,
    redis_client,
    settings,
) -> dict:
    result = {"render_paths": None, "price": None, "measurement": None, "order": None}
    if not actions.actions:
        return result
    render_created_order = False
    system_collected_patch: dict[str, str] = {}
    current_mode = (conversation_state or {}).get("mode") or "idle"
    pending_state_patch = ensure_json_object(actions.actions.get("state_patch"))
    current_collected = ensure_json_object((conversation_state or {}).get("collected_params", {}))
    patch_collected = ensure_json_object(pending_state_patch.get("collected_params"))
    merged_collected = {**current_collected, **patch_collected}
    requested_mode = pending_state_patch.get("mode")
    has_schedule_measurement = bool(actions.actions.get("schedule_measurement"))
    suppress_render_for_measurement = has_schedule_measurement and (
        current_mode in {"rendering", "scheduling"} or requested_mode == "scheduling"
    )
    rendered_draft = None
    if actions.actions.get("render_partition") or actions.actions.get("schedule_measurement"):
        rendered_draft = await postgres.get_rendered_order_draft(pg_pool, chat_id)
        if rendered_draft:
            rendered_order_id = rendered_draft.get("rendered_order_id") or rendered_draft.get("request_id")
            if rendered_order_id:
                system_collected_patch["_rendered_order_id"] = str(rendered_order_id)

    if actions.actions.get("cancel_order"):
        await postgres.abandon_current_order_draft(pg_pool, chat_id, cancel_order=True)
        rendered_draft = None
        current_collected.pop("_rendered_order_id", None)
        patch_collected.pop("_rendered_order_id", None)
        merged_collected.pop("_rendered_order_id", None)
        system_collected_patch.pop("_rendered_order_id", None)
        result["order_cancelled"] = True

    if actions.actions.get("update_client_profile"):
        params = UpdateClientProfileAction(**actions.actions["update_client_profile"])
        await postgres.update_client(
            pg_pool,
            chat_id,
            name=params.name,
            phone=params.phone,
            address=params.address,
        )

    if actions.actions.get("render_partition"):
        if suppress_render_for_measurement:
            logger.info(
                "render_suppressed_during_measurement_flow",
                extra={"chat_id": chat_id, "current_mode": current_mode, "requested_mode": requested_mode},
            )
            result["render_suppressed"] = True
        else:
            existing_order = _order_from_rendered_draft(rendered_draft)
            normalized = merge_render_params(merged_collected, actions.actions["render_partition"])
            missing = missing_render_params(normalized)

            is_reusable = False
            if existing_order and not missing:
                try:
                    params = RenderPartitionAction(**normalized)
                    normalized_current = normalize_render_params(params.model_dump(exclude_none=True))
                    old_details = existing_order.get("details_json", {})
                    is_reusable = True
                    for key in ["shape", "partition_type", "height", "width_a", "width_b", "width_c", "glass_type", "frame_color", "matting", "add_handle", "rows", "cols", "shape_side", "handle_sections", "handle_wall"]:
                        curr_val = normalized_current.get(key)
                        old_val = old_details.get(key)
                        if curr_val != old_val and str(curr_val) != str(old_val):
                            is_reusable = False
                            break
                except Exception:
                    is_reusable = False

            if is_reusable:
                logger.info(
                    "render_reused_existing_order",
                    extra={"chat_id": chat_id, "request_id": existing_order["request_id"]},
                )
                result["order"] = existing_order
                result["render_paths"] = existing_order.get("render_paths")
                result["price"] = existing_order.get("price")
                result["render_reused"] = True
            else:
                if existing_order:
                    # Clean up the stale rendered draft reference so we force a new one
                    system_collected_patch.pop("_rendered_order_id", None)
                if missing:
                    logger.warning(
                        "render_blocked_missing_params",
                        extra={"chat_id": chat_id, "missing": missing},
                    )
                    result["render_missing_params"] = missing
                else:
                    params = RenderPartitionAction(**normalized)
                    normalized = normalize_render_params(params.model_dump(exclude_none=True))
                    draft = await postgres.get_active_order_draft(pg_pool, chat_id)
                    if draft:
                        request_id = draft["request_id"]
                        await postgres.upsert_order_draft(
                            pg_pool,
                            chat_id,
                            normalized,
                            status="rendering",
                            request_id=request_id,
                        )
                    else:
                        request_id = str(uuid4())
                        await postgres.upsert_order_draft(
                            pg_pool,
                            chat_id,
                            normalized,
                            status="rendering",
                            request_id=request_id,
                        )
                    await pricing_cache.reload(pg_pool)
                    render_result = await render_partition(params, request_id, settings)
                    price = calculate_price(
                        shape=normalized["shape"],
                        height=float(normalized["height"]),
                        width_a=float(normalized["width_a"]),
                        width_b=float(normalized.get("width_b") or 0),
                        width_c=float(normalized.get("width_c") or 0),
                        glass_type=str(normalized.get("glass_type") or "1"),
                        frame_color=str(normalized.get("frame_color") or "1"),
                        rows=int(normalized.get("rows") or 1),
                        cols=int(normalized.get("cols") or 2),
                        add_handle=bool(normalized.get("add_handle")),
                        partition_type=str(normalized.get("partition_type") or "sliding_2"),
                        matting=str(normalized.get("matting") or "none"),
                        complex_pattern=bool(normalized.get("complex_pattern")),
                        cache=pricing_cache,
                    )
                    order = await postgres.create_order(
                        pg_pool,
                        request_id=request_id,
                        chat_id=chat_id,
                        details_json=normalized,
                        render_paths=render_result["render_paths"],
                        price=price,
                    )
                    result.update({"render_paths": render_result["render_paths"], "price": price, "order": order})
                    await postgres.mark_active_order_draft_rendered(pg_pool, chat_id, request_id)
                    render_created_order = True
                    system_collected_patch["_rendered_order_id"] = request_id

                    for manager_chat_id in settings.manager_chat_ids_list:
                        await telegram_sender.send_message(
                            settings.manager_bot_token,
                            manager_chat_id,
                            (
                                "<b>Новый расчёт Shermos</b>\n"
                                f"Заказ: <code>{request_id}</code>\n"
                                f"Клиент chat_id: <code>{chat_id}</code>\n"
                                f"Сумма: <b>{price['total_price']} {price['currency']}</b>"
                            ),
                        )
                    for manager_phone in getattr(settings, "manager_whatsapp_numbers_list", []):
                        await _send_manager_whatsapp_notification(
                            manager_phone,
                            (
                                "<b>Новый расчёт Shermos</b>\n"
                                f"Заказ: <code>{request_id}</code>\n"
                                f"Клиент chat_id: <code>{chat_id}</code>\n"
                                f"Сумма: <b>{price['total_price']} {price['currency']}</b>"
                            ),
                        )

    if actions.actions.get("schedule_measurement"):
        missing_measurement_fields = _missing_measurement_fields(merged_collected)
        if missing_measurement_fields:
            missing_text = ", ".join(missing_measurement_fields)
            raise ValueError(f"Чтобы записать на замер, мне нужно уточнить: {missing_text}.")

        params = ScheduleMeasurementAction(**_measurement_state_payload(merged_collected))

        # Update client profile with provided contact info
        await postgres.update_client(
            pg_pool,
            chat_id,
            name=params.client_name,
            phone=params.phone,
            address=params.address,
        )

        # Schedule with conflict detection (raises ValueError on conflict)
        measurement = await schedule_measurement(
            pool=pg_pool,
            chat_id=chat_id,
            date=params.date,
            time=params.time,
            client_name=params.client_name,
            phone=params.phone,
            address=params.address,
            timezone=settings.timezone,
            order_request_id=(
                system_collected_patch.get("_rendered_order_id")
                or str(merged_collected.get("_rendered_order_id") or "").strip()
                or None
            ),
        )
        result["measurement"] = measurement

        # Notify ALL managers about new measurement
        m_id = measurement["id"]
        m_time = measurement["scheduled_time"].strftime("%d.%m.%Y %H:%M")
        order_request_id = measurement.get("order_request_id")
        order_line = f"Заказ: <code>{order_request_id}</code>\n" if order_request_id else ""
        for manager_chat_id in settings.manager_chat_ids_list:
            await telegram_sender.send_message(
                settings.manager_bot_token,
                manager_chat_id,
                (
                    "<b>Новая запись на замер</b>\n\n"
                    f"{order_line}"
                    f"Клиент: <b>{params.client_name}</b>\n"
                    f"Телефон: {params.phone}\n"
                    f"Адрес: {params.address or '—'}\n"
                    f"Время: <b>{m_time}</b>\n"
                    f"Замер: <code>#{m_id}</code>\n\n"
                    "Если не подтвердить и не отклонить за 15 минут, замер подтвердится автоматически."
                ),
                reply_markup=manager_measurement_keyboard(m_id),
            )
        for manager_phone in getattr(settings, "manager_whatsapp_numbers_list", []):
            await _send_manager_whatsapp_notification(
                manager_phone,
                (
                    "<b>Новая запись на замер</b>\n\n"
                    f"{order_line}"
                    f"Клиент: <b>{params.client_name}</b>\n"
                    f"Телефон: {params.phone}\n"
                    f"Адрес: {params.address or '—'}\n"
                    f"Время: <b>{m_time}</b>\n"
                    f"Замер: <code>#{m_id}</code>\n\n"
                    "Если не подтвердить и не отклонить за 15 минут, замер подтвердится автоматически."
                ),
                reply_markup=manager_measurement_keyboard(m_id),
            )

    if actions.actions.get("state_patch"):
        patch = StatePatch(**actions.actions["state_patch"])
        current_mode = (conversation_state or {}).get("mode", "idle")
        next_mode = patch.mode or current_mode
        if not is_valid_transition(current_mode, next_mode):
            next_mode = current_mode
        next_collected = (
            {**current_collected, **patch_collected, **system_collected_patch}
            if patch.collected_params is not None
            else {**current_collected, **system_collected_patch}
        )
        if result.get("measurement"):
            for key in _MEASUREMENT_FIELD_MAP:
                next_collected.pop(key, None)
            if next_mode == "scheduling":
                patch.step = "measurement_scheduled"
        await postgres.upsert_conversation_state(
            pg_pool,
            chat_id,
            next_mode,
            patch.step,
            next_collected,
        )
        if (
            next_collected
            and not render_created_order
            and next_mode in {"collecting", "confirming"}
            and not next_collected.get("_rendered_order_id")
        ):
            draft_status = "confirming" if next_mode == "confirming" else "collecting"
            await postgres.upsert_order_draft(pg_pool, chat_id, next_collected, status=draft_status)
    elif system_collected_patch:
        await postgres.upsert_conversation_state(
            pg_pool,
            chat_id,
            current_mode,
            (conversation_state or {}).get("step"),
            {**current_collected, **system_collected_patch},
        )

    return result

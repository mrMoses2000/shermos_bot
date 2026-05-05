"""Execute validated LLM actions."""

from __future__ import annotations

from uuid import uuid4

from src.bot.keyboards import manager_measurement_keyboard
from src.db import postgres
from src.engine.fsm import is_valid_transition
from src.engine.measurement_service import (
    get_active_measurement_for_chat,
    schedule_measurement,
    update_measurement,
)
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
    UpdateMeasurementAction,
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
    current_step = (conversation_state or {}).get("step")
    if has_schedule_measurement:
        # Block scheduling if it's clearly out of context
        is_scheduling_intent = (requested_mode == "scheduling")
        is_safe_scheduling_mode = (current_mode == "scheduling")
        
        if not (is_scheduling_intent or is_safe_scheduling_mode):
            logger.warning("schedule_measurement_blocked_wrong_mode", extra={"chat_id": chat_id, "requested_mode": requested_mode, "current_mode": current_mode})
            has_schedule_measurement = False
            actions.actions.pop("schedule_measurement", None)
        elif not is_scheduling_intent and current_step in {"materials", "dims", "shape"}:
            # Even if in scheduling mode, if we are currently at materials/dims step and LLM didn't EXPLICITLY set mode=scheduling this turn,
            # it's likely a hallucination or stale fields trigger.
            logger.warning("schedule_measurement_blocked_wrong_step", extra={"chat_id": chat_id, "step": current_step})
            has_schedule_measurement = False
            actions.actions.pop("schedule_measurement", None)

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
        
        for key in _MEASUREMENT_FIELD_MAP:
            current_collected.pop(key, None)
            patch_collected.pop(key, None)
            merged_collected.pop(key, None)
            system_collected_patch.pop(key, None)
            
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
                    for key in RenderPartitionAction.model_fields.keys():
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

                    _new_order_text = (
                        "<b>Новый расчёт Shermos</b>\n"
                        f"Заказ: <code>{request_id}</code>\n"
                        f"Клиент chat_id: <code>{chat_id}</code>\n"
                        f"Сумма: <b>{price['total_price']} {price['currency']}</b>"
                    )
                    for manager_phone in getattr(settings, "manager_whatsapp_numbers_list", []):
                        await postgres.insert_outbound_event(
                            pg_pool,
                            chat_id=int(manager_phone),
                            channel="whatsapp",
                            external_chat_id=f"{manager_phone}@s.whatsapp.net",
                            reply_text=_new_order_text,
                            reply_markup=None,
                            bot_type="manager",
                            idempotency_key=f"new_order:{request_id}:{manager_phone}",
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
        # Remember measurement id in state so subsequent edits go through
        # update_measurement instead of re-running schedule_measurement.
        system_collected_patch["_measurement_id"] = int(measurement["id"])

        # Notify ALL managers about new measurement
        m_id = measurement["id"]
        from src.utils.datetime_format import fmt_local
        m_time = fmt_local(measurement["scheduled_time"], "%d.%m.%Y %H:%M")
        order_request_id = measurement.get("order_request_id")
        order_line = f"Заказ: <code>{order_request_id}</code>\n" if order_request_id else ""
        _new_measurement_text = (
            "<b>Новая запись на замер</b>\n\n"
            f"{order_line}"
            f"Клиент: <b>{params.client_name}</b>\n"
            f"Телефон: {params.phone}\n"
            f"Адрес: {params.address or '—'}\n"
            f"Время: <b>{m_time}</b>\n"
            f"Замер: <code>#{m_id}</code>\n\n"
            "Если не подтвердить и не отклонить за 15 минут, замер подтвердится автоматически."
        )
        for manager_phone in getattr(settings, "manager_whatsapp_numbers_list", []):
            await postgres.insert_outbound_event(
                pg_pool,
                chat_id=int(manager_phone),
                channel="whatsapp",
                external_chat_id=f"{manager_phone}@s.whatsapp.net",
                reply_text=_new_measurement_text,
                reply_markup=manager_measurement_keyboard(m_id),
                bot_type="manager",
                idempotency_key=f"new_measurement:{m_id}:{manager_phone}",
            )

    if actions.actions.get("update_measurement"):
        params = UpdateMeasurementAction(**actions.actions["update_measurement"])

        # Resolve measurement_id: prefer explicit, then state, then active row in DB.
        m_id = params.measurement_id
        if m_id is None:
            stored = current_collected.get("_measurement_id")
            try:
                m_id = int(stored) if stored is not None else None
            except (TypeError, ValueError):
                m_id = None
        if m_id is None:
            active = await get_active_measurement_for_chat(pg_pool, chat_id)
            if active:
                m_id = int(active["id"])
        if m_id is None:
            raise ValueError("Не нашёл активный замер для обновления — запишитесь сначала.")

        # Update client profile if name/phone/address provided (mirror schedule_measurement).
        if any(x is not None for x in (params.client_name, params.phone, params.address)):
            await postgres.update_client(
                pg_pool, chat_id,
                name=params.client_name, phone=params.phone, address=params.address,
            )

        measurement = await update_measurement(
            pool=pg_pool,
            measurement_id=m_id,
            date=params.date,
            time=params.time,
            timezone=settings.timezone,
            client_name=params.client_name,
            client_phone=params.phone,
            address=params.address,
        )
        result["measurement"] = measurement
        system_collected_patch["_measurement_id"] = int(measurement["id"])
        # Mirror provided fields back into collected_params so state stays consistent.
        if params.date:
            system_collected_patch["measurement_date"] = params.date
        if params.time:
            system_collected_patch["measurement_time"] = params.time
        if params.client_name is not None:
            system_collected_patch["measurement_name"] = params.client_name
        if params.phone is not None:
            system_collected_patch["measurement_phone"] = params.phone
        if params.address is not None:
            system_collected_patch["measurement_address"] = params.address

        # Notify managers about the change (best-effort via outbox).
        from src.utils.datetime_format import fmt_local
        m_time = fmt_local(measurement["scheduled_time"], "%d.%m.%Y %H:%M")
        changed_lines = []
        if params.date or params.time:
            changed_lines.append(f"⏰ Новое время: <b>{m_time}</b>")
        if params.address:
            changed_lines.append(f"📍 Новый адрес: {params.address}")
        if params.client_name:
            changed_lines.append(f"👤 Имя: {params.client_name}")
        if params.phone:
            changed_lines.append(f"📞 Телефон: {params.phone}")
        notify_text = (
            f"<b>Замер #{m_id} обновлён клиентом</b>\n\n"
            + "\n".join(changed_lines)
        ) if changed_lines else None

        if notify_text:
            for manager_phone in getattr(settings, "manager_whatsapp_numbers_list", []):
                await postgres.insert_outbound_event(
                    pg_pool,
                    chat_id=int(manager_phone),
                    channel="whatsapp",
                    external_chat_id=f"{manager_phone}@s.whatsapp.net",
                    reply_text=notify_text,
                    reply_markup=None,
                    bot_type="manager",
                    idempotency_key=f"meas_updated:{m_id}:{int(measurement.get('updated_at', measurement['scheduled_time']).timestamp())}:{manager_phone}",
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

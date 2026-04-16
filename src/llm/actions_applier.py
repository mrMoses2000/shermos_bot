"""Execute validated LLM actions."""

from __future__ import annotations

from uuid import uuid4

from src.bot.keyboards import manager_measurement_keyboard
from src.bot.telegram_sender import telegram_sender
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
        current_collected = ensure_json_object((conversation_state or {}).get("collected_params", {}))
        pending_state_patch = ensure_json_object(actions.actions.get("state_patch"))
        current_collected.update(ensure_json_object(pending_state_patch.get("collected_params")))
        normalized = merge_render_params(current_collected, actions.actions["render_partition"])
        missing = missing_render_params(normalized)
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
                await postgres.upsert_order_draft(pg_pool, chat_id, normalized, status="rendering", request_id=request_id)
            else:
                request_id = str(uuid4())
                await postgres.upsert_order_draft(pg_pool, chat_id, normalized, status="rendering", request_id=request_id)
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

    if actions.actions.get("schedule_measurement"):
        params = ScheduleMeasurementAction(**actions.actions["schedule_measurement"])

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
        )
        result["measurement"] = measurement

        # Notify ALL managers about new measurement
        m_id = measurement["id"]
        m_time = measurement["scheduled_time"].strftime("%d.%m.%Y %H:%M")
        for manager_chat_id in settings.manager_chat_ids_list:
            await telegram_sender.send_message(
                settings.manager_bot_token,
                manager_chat_id,
                (
                    "<b>Новая запись на замер</b>\n\n"
                    f"Клиент: <b>{params.client_name}</b>\n"
                    f"Телефон: {params.phone}\n"
                    f"Адрес: {params.address or '—'}\n"
                    f"Время: <b>{m_time}</b>\n"
                    f"Замер: <code>#{m_id}</code>"
                ),
                reply_markup=manager_measurement_keyboard(m_id),
            )

    if actions.actions.get("state_patch"):
        patch = StatePatch(**actions.actions["state_patch"])
        current_mode = (conversation_state or {}).get("mode", "idle")
        next_mode = patch.mode or current_mode
        if not is_valid_transition(current_mode, next_mode):
            next_mode = current_mode
        current_collected = ensure_json_object((conversation_state or {}).get("collected_params", {}))
        patch_collected = ensure_json_object(patch.collected_params)
        next_collected = {**current_collected, **patch_collected} if patch.collected_params is not None else current_collected
        await postgres.upsert_conversation_state(
            pg_pool,
            chat_id,
            next_mode,
            patch.step,
            next_collected,
        )
        if next_collected and not render_created_order:
            draft_status = "confirming" if next_mode == "confirming" else "collecting"
            await postgres.upsert_order_draft(pg_pool, chat_id, next_collected, status=draft_status)

    return result

"""Execute validated LLM actions."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from src.bot.telegram_sender import telegram_sender
from src.db import postgres
from src.engine.calendar_engine import create_measurement_event
from src.engine.fsm import is_valid_transition
from src.engine.pricing_engine import calculate_price
from src.engine.render_engine import render_partition
from src.models import (
    ActionsJson,
    RenderPartitionAction,
    ScheduleMeasurementAction,
    StatePatch,
    UpdateClientProfileAction,
)
from src.utils.query_parser import normalize_render_params


async def apply_actions(
    actions: ActionsJson,
    chat_id: int,
    client_profile: dict | None,
    conversation_state: dict | None,
    pg_pool,
    redis_client,
    settings,
) -> dict:
    result = {"render_paths": None, "price": None, "calendar_event": None, "order": None}
    if not actions.actions:
        return result

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
        params = RenderPartitionAction(**actions.actions["render_partition"])
        normalized = normalize_render_params(params.model_dump(exclude_none=True))
        request_id = str(uuid4())
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

        for manager_chat_id in settings.manager_chat_ids_list:
            await telegram_sender.send_message(
                settings.manager_bot_token,
                manager_chat_id,
                (
                    "<b>Новый расчет Shermos</b>\n"
                    f"Заказ: <code>{request_id}</code>\n"
                    f"Клиент chat_id: <code>{chat_id}</code>\n"
                    f"Сумма: <b>{price['total_price']} {price['currency']}</b>"
                ),
            )

    if actions.actions.get("schedule_measurement"):
        params = ScheduleMeasurementAction(**actions.actions["schedule_measurement"])
        calendar_event = await create_measurement_event(
            params.date,
            params.time,
            params.client_name,
            params.phone,
            params.address,
            settings,
        )
        await postgres.update_client(
            pg_pool,
            chat_id,
            name=params.client_name,
            phone=params.phone,
            address=params.address,
        )
        await postgres.create_measurement(
            pg_pool,
            client_chat_id=chat_id,
            scheduled_time=datetime.fromisoformat(calendar_event["start"]),
            address=params.address,
            notes="Создано ботом",
            calendar_event_id=calendar_event["event_id"],
        )
        result["calendar_event"] = calendar_event

    if actions.actions.get("state_patch"):
        patch = StatePatch(**actions.actions["state_patch"])
        current_mode = (conversation_state or {}).get("mode", "idle")
        next_mode = patch.mode or current_mode
        if not is_valid_transition(current_mode, next_mode):
            next_mode = current_mode
        await postgres.upsert_conversation_state(
            pg_pool,
            chat_id,
            next_mode,
            patch.step,
            patch.collected_params or (conversation_state or {}).get("collected_params", {}),
        )

    return result

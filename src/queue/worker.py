"""Main Redis worker pipeline for client and manager bots."""

from __future__ import annotations

import asyncio
from typing import Any

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.bot.keyboards import manager_measurement_keyboard, open_mini_app_keyboard, rate_render_keyboard
from src.bot.telegram_sender import TelegramSender, telegram_sender
from src.config import settings
from src.db import postgres
from src.db.redis_client import RedisClient
from src.llm.actions_applier import apply_actions
from src.llm.actions_parser import parse_actions
from src.llm.executor import call_llm
from src.llm.health_check import run_gemini_health_check
from src.llm.prompt_builder import build_prompt
from src.models import Job
from src.queue.outbox_dispatcher import run_outbox_dispatcher
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def _load_available_slots(pg_pool, days_ahead: int = 3) -> dict[str, list[str]]:
    """Load available measurement slots for the next N days."""
    from src.engine.measurement_service import get_available_slots

    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    slots = {}
    for i in range(days_ahead):
        day = today + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        try:
            day_slots = await get_available_slots(pg_pool, date_str, settings.timezone)
            slots[date_str] = day_slots
        except Exception:
            slots[date_str] = []
    return slots


CLIENT_COMMANDS = {
    "/start": (
        "Здравствуйте! Я помогу рассчитать стеклянную перегородку Shermos.\n"
        "Опишите форму, размеры, тип стекла и цвет профиля. Например: "
        "прямая перегородка 3 на 2.6 м, черный профиль, прозрачное стекло."
    ),
    "/help": (
        "<b>Что я умею</b>\n"
        "1. Собрать параметры перегородки.\n"
        "2. Сделать 3D-рендер.\n"
        "3. Рассчитать ориентировочную стоимость.\n"
        "4. Записать на замер."
    ),
    "/examples": (
        "Примеры:\n"
        "• Прямая перегородка шириной 3 м, высота 2.7 м.\n"
        "• Г-образная 2.5 на 1.2 м, рифленое стекло.\n"
        "• Хочу замер завтра в 15:30."
    ),
}


async def _send_and_record(
    pg_pool,
    sender: TelegramSender,
    token: str,
    chat_id: int,
    text: str,
    bot_type: str = "client",
    reply_markup: dict | None = None,
) -> None:
    event_id = await postgres.insert_outbound_event(
        pg_pool,
        chat_id=chat_id,
        reply_text=text,
        reply_markup=reply_markup,
        bot_type=bot_type,
    )
    msg_id = await sender.send_message(token, chat_id, text, reply_markup=reply_markup)
    await postgres.mark_outbound_sent(pg_pool, event_id, telegram_message_id=msg_id)


def _telegram_user(job: Job) -> tuple[str, str]:
    message = job.raw_update.get("message") or {}
    user = message.get("from") or {}
    return user.get("first_name", ""), user.get("username", "")


async def _handle_client_command(job: Job, pg_pool, sender: TelegramSender) -> bool:
    text = (job.text or "").split()[0].lower()
    if text == "/clear":
        await postgres.clear_chat_messages(pg_pool, job.chat_id)
        await postgres.upsert_conversation_state(pg_pool, job.chat_id, "idle", None, {})
        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            "История диалога очищена.",
        )
        return True
    if text == "/status":
        orders = await postgres.list_orders(pg_pool, search=str(job.chat_id), limit=5)
        if not orders:
            reply = "У вас пока нет расчетов."
        else:
            lines = ["<b>Последние расчеты:</b>"]
            for order in orders:
                price = order.get("price") or {}
                lines.append(
                    f"• <code>{order['request_id']}</code> — {order['status']}, "
                    f"{price.get('total_price', '—')} {price.get('currency', '')}"
                )
            reply = "\n".join(lines)
        await _send_and_record(pg_pool, sender, settings.telegram_bot_token, job.chat_id, reply)
        return True
    if text in CLIENT_COMMANDS:
        first_name, username = _telegram_user(job)
        await postgres.create_client(pg_pool, job.chat_id, first_name, username)
        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            CLIENT_COMMANDS[text],
        )
        return True
    return False


async def _send_render_result(job: Job, pg_pool, sender: TelegramSender, action_result: dict[str, Any]) -> None:
    render_paths = action_result.get("render_paths")
    if not render_paths:
        return
    order = action_result.get("order") or {}
    price = action_result.get("price") or {}
    paths = [render_paths[key] for key in sorted(render_paths.keys())]
    caption = (
        f"<b>Рендер готов</b>\n"
        f"Заказ: <code>{order.get('request_id', '')}</code>\n"
        f"Стоимость: <b>{price.get('total_price')} {price.get('currency')}</b>"
    )
    if len(paths) == 1:
        await sender.send_photo(settings.telegram_bot_token, job.chat_id, paths[0], caption=caption)
    else:
        await sender.send_media_group(settings.telegram_bot_token, job.chat_id, paths, caption=caption)
    await sender.send_message(
        settings.telegram_bot_token,
        job.chat_id,
        "Оцените, пожалуйста, рендер:",
        reply_markup=rate_render_keyboard(order.get("request_id", "")),
    )


async def process_client_job(
    job: Job,
    pg_pool,
    redis_client: RedisClient,
    sender: TelegramSender = telegram_sender,
) -> None:
    locked = await redis_client.acquire_user_lock(job.chat_id, ttl=180)
    if not locked:
        if job.attempt < 5:
            await asyncio.sleep(min(2**job.attempt, 30))
            await redis_client.enqueue_job("queue:incoming", job.model_copy(update={"attempt": job.attempt + 1}))
        return

    try:
        await postgres.mark_update_status(pg_pool, job.update_id, "processing")
        if settings.send_typing_indicator:
            await sender.send_chat_action(settings.telegram_bot_token, job.chat_id)

        if job.msg_type == "command" and await _handle_client_command(job, pg_pool, sender):
            await postgres.mark_update_status(pg_pool, job.update_id, "completed")
            return

        first_name, username = _telegram_user(job)
        client = await postgres.get_client_by_chat_id(pg_pool, job.chat_id)
        if not client:
            client = await postgres.create_client(pg_pool, job.chat_id, first_name, username)
        state = await postgres.get_conversation_state(pg_pool, job.chat_id)
        history = await postgres.get_chat_messages(pg_pool, job.chat_id, settings.max_context_messages)

        # Load available measurement slots for the next 3 days
        available_slots = await _load_available_slots(pg_pool)

        prompt = build_prompt(job.text, client, state, history, available_slots=available_slots)
        raw_llm = await call_llm(prompt)
        parsed = parse_actions(raw_llm)
        action_result = await apply_actions(parsed, job.chat_id, client, state, pg_pool, redis_client, settings)

        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            parsed.reply_text,
        )
        await _send_render_result(job, pg_pool, sender, action_result)
        await postgres.insert_chat_message(pg_pool, job.chat_id, "user", job.text)
        await postgres.insert_chat_message(pg_pool, job.chat_id, "assistant", parsed.reply_text)
        await postgres.mark_update_status(pg_pool, job.update_id, "completed")
    except TimeoutError as exc:
        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            "Запрос занял слишком много времени. Попробуйте еще раз.",
        )
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", str(exc))
    except Exception as exc:
        logger.exception("client_job_failed", extra={"update_id": job.update_id, "error": str(exc)})
        try:
            await _send_and_record(
                pg_pool,
                sender,
                settings.telegram_bot_token,
                job.chat_id,
                "Произошла ошибка. Попробуйте еще раз или напишите менеджеру.",
            )
        finally:
            await postgres.mark_update_status(pg_pool, job.update_id, "failed", str(exc))
    finally:
        await redis_client.release_user_lock(job.chat_id)


async def pool_fetchrow_safe(pg_pool, measurement_id: int) -> dict | None:
    row = await pg_pool.fetchrow("SELECT * FROM measurements WHERE id=$1", measurement_id)
    return dict(row) if row else None


async def _handle_measurement_callback(
    text: str,
    job: Job,
    pg_pool,
    sender: TelegramSender,
) -> None:
    """Handle meas_confirm:{id} and meas_reject:{id} callbacks from manager."""
    from src.engine.measurement_service import update_measurement_status

    parts = text.split(":")
    action = parts[0]  # meas_confirm or meas_reject
    meas_id = int(parts[1])
    new_status = "confirmed" if action == "meas_confirm" else "rejected"

    try:
        measurement = await update_measurement_status(
            pg_pool, meas_id, new_status, manager_chat_id=job.chat_id
        )
    except ValueError as exc:
        await _send_and_record(
            pg_pool, sender, settings.manager_bot_token, job.chat_id,
            f"Ошибка: {exc}", bot_type="manager",
        )
        return

    m_time = measurement["scheduled_time"].strftime("%d.%m.%Y %H:%M")
    status_text = "подтверждён" if new_status == "confirmed" else "отклонён"

    # Notify manager
    await _send_and_record(
        pg_pool, sender, settings.manager_bot_token, job.chat_id,
        f"Замер #{meas_id} ({m_time}) — <b>{status_text}</b>.",
        bot_type="manager",
    )

    # Notify CLIENT about the decision
    client_chat_id = measurement["client_chat_id"]
    if new_status == "confirmed":
        client_msg = (
            f"<b>Ваш замер подтверждён!</b>\n\n"
            f"Дата: <b>{m_time}</b>\n"
            f"Адрес: {measurement.get('address', '—')}\n\n"
            f"Мастер приедет в указанное время. "
            f"Если нужно перенести — напишите нам."
        )
    else:
        client_msg = (
            f"К сожалению, замер на <b>{m_time}</b> не может быть проведён.\n\n"
            f"Напишите нам, чтобы выбрать другое время."
        )

    await _send_and_record(
        pg_pool, sender, settings.telegram_bot_token, client_chat_id,
        client_msg, bot_type="client",
    )


async def process_manager_job(
    job: Job,
    pg_pool,
    redis_client: RedisClient,
    sender: TelegramSender = telegram_sender,
) -> None:
    try:
        await postgres.mark_update_status(pg_pool, job.update_id, "processing")
        text = (job.text or job.callback_data or "").strip()
        if text.startswith("/start") or text.startswith("/health"):
            reply_markup = open_mini_app_keyboard(settings.mini_app_url) if settings.mini_app_url else None
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                "Shermos manager bot работает.",
                bot_type="manager",
                reply_markup=reply_markup,
            )
        elif text.startswith("/orders"):
            orders = await postgres.list_orders(pg_pool, limit=10)
            lines = ["<b>Последние заказы:</b>"]
            for order in orders:
                lines.append(f"• <code>{order['request_id']}</code> — {order['status']}")
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                "\n".join(lines) if orders else "Заказов пока нет.",
                bot_type="manager",
            )
        elif text.startswith("order_status:"):
            _prefix, order_id, status = text.split(":", 2)
            await postgres.update_order_status(pg_pool, order_id, status)
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                f"Статус заказа <code>{order_id}</code> обновлен: {status}",
                bot_type="manager",
            )
        elif text.startswith("meas_confirm:") or text.startswith("meas_reject:"):
            await _handle_measurement_callback(text, job, pg_pool, sender)
        elif text.startswith("meas_call:"):
            meas_id = int(text.split(":")[1])
            meas = await pool_fetchrow_safe(pg_pool, meas_id)
            phone = meas.get("client_phone", "") if meas else ""
            reply = f"Телефон клиента: {phone}" if phone else "Телефон не указан."
            await _send_and_record(pg_pool, sender, settings.manager_bot_token, job.chat_id, reply, bot_type="manager")
        elif text.startswith("/measurements"):
            measurements = await postgres.list_measurements(pg_pool, upcoming_only=True, limit=10)
            lines = ["<b>Ближайшие замеры:</b>"]
            for m in measurements:
                t = m["scheduled_time"].strftime("%d.%m %H:%M")
                lines.append(f"• #{m['id']} {t} — {m.get('client_name', '—')} ({m['status']})")
            await _send_and_record(
                pg_pool, sender, settings.manager_bot_token, job.chat_id,
                "\n".join(lines) if measurements else "Замеров пока нет.",
                bot_type="manager",
            )
        else:
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                "Команды: /orders, /health",
                bot_type="manager",
            )
        await postgres.mark_update_status(pg_pool, job.update_id, "completed")
    except Exception as exc:
        logger.exception("manager_job_failed", extra={"update_id": job.update_id, "error": str(exc)})
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", str(exc))


async def _client_loop(pg_pool, redis_client: RedisClient, sender: TelegramSender) -> None:
    while True:
        try:
            job = await redis_client.dequeue_job_safe("queue:incoming", "queue:processing:client", timeout=5)
            if job is not None:
                try:
                    await process_client_job(job, pg_pool, redis_client, sender)
                finally:
                    await redis_client.ack_job("queue:processing:client", job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("client_loop_error", extra={"error": str(exc)})
            await asyncio.sleep(5)


async def _manager_loop(pg_pool, redis_client: RedisClient, sender: TelegramSender) -> None:
    while True:
        try:
            job = await redis_client.dequeue_job_safe("queue:manager", "queue:processing:manager", timeout=5)
            if job is not None:
                try:
                    await process_manager_job(job, pg_pool, redis_client, sender)
                finally:
                    await redis_client.ack_job("queue:processing:manager", job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("manager_loop_error", extra={"error": str(exc)})
            await asyncio.sleep(5)


async def run_worker() -> None:
    pg_pool = await postgres.create_pool(settings)
    await postgres.run_migrations(pg_pool)
    await postgres.seed_default_prices(pg_pool)
    await postgres.seed_default_materials(pg_pool)
    redis_client = RedisClient(settings.redis_url)
    await redis_client.connect()
    await telegram_sender.start()
    recovered = await redis_client.recover_stuck_jobs("queue:processing:client", "queue:incoming")
    if recovered:
        logger.info("recovered_stuck_jobs", extra={"count": recovered, "queue": "client"})
    recovered_mgr = await redis_client.recover_stuck_jobs("queue:processing:manager", "queue:manager")
    if recovered_mgr:
        logger.info("recovered_stuck_jobs", extra={"count": recovered_mgr, "queue": "manager"})
    tasks = [
        asyncio.create_task(_client_loop(pg_pool, redis_client, telegram_sender)),
        asyncio.create_task(_manager_loop(pg_pool, redis_client, telegram_sender)),
        asyncio.create_task(run_outbox_dispatcher(pg_pool, telegram_sender)),
        asyncio.create_task(run_gemini_health_check()),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await redis_client.close()
        await telegram_sender.close()
        await postgres.close_pool(pg_pool)

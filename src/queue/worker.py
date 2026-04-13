"""Main Redis worker pipeline for client and manager bots."""

from __future__ import annotations

import asyncio
from typing import Any

from src.bot.keyboards import open_mini_app_keyboard, rate_render_keyboard
from src.bot.telegram_sender import TelegramSender, telegram_sender
from src.config import settings
from src.db import postgres
from src.db.redis_client import RedisClient
from src.llm.actions_applier import apply_actions
from src.llm.actions_parser import parse_actions
from src.llm.executor import call_llm
from src.llm.prompt_builder import build_prompt
from src.models import Job
from src.queue.outbox_dispatcher import run_outbox_dispatcher
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


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
    await sender.send_message(token, chat_id, text, reply_markup=reply_markup)
    await postgres.mark_outbound_sent(pg_pool, event_id)


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
        prompt = build_prompt(job.text, client, state, history)
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
        job = await redis_client.dequeue_job("queue:incoming", timeout=5)
        if job is not None:
            await process_client_job(job, pg_pool, redis_client, sender)


async def _manager_loop(pg_pool, redis_client: RedisClient, sender: TelegramSender) -> None:
    while True:
        job = await redis_client.dequeue_job("queue:manager", timeout=5)
        if job is not None:
            await process_manager_job(job, pg_pool, redis_client, sender)


async def run_worker() -> None:
    pg_pool = await postgres.create_pool(settings)
    await postgres.run_migrations(pg_pool)
    await postgres.seed_default_prices(pg_pool)
    await postgres.seed_default_materials(pg_pool)
    redis_client = RedisClient(settings.redis_url)
    await redis_client.connect()
    await telegram_sender.start()
    tasks = [
        asyncio.create_task(_client_loop(pg_pool, redis_client, telegram_sender)),
        asyncio.create_task(_manager_loop(pg_pool, redis_client, telegram_sender)),
        asyncio.create_task(run_outbox_dispatcher(pg_pool, telegram_sender)),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await redis_client.close()
        await telegram_sender.close()
        await postgres.close_pool(pg_pool)

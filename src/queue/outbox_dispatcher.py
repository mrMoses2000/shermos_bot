"""Retry loop for pending Telegram outbound events."""

from __future__ import annotations

import asyncio

from src.bot.telegram_sender import TelegramSender, telegram_sender
from src.config import settings
from src.db import postgres
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def dispatch_once(pg_pool, sender: TelegramSender = telegram_sender) -> int:
    events = await postgres.get_pending_outbound(pg_pool, limit=20)
    sent = 0
    for event in events:
        if event.get("telegram_message_id"):
            await postgres.mark_outbound_sent(
                pg_pool,
                int(event["id"]),
                int(event["telegram_message_id"]),
            )
            continue
        token = settings.manager_bot_token if event.get("bot_type") == "manager" else settings.telegram_bot_token
        try:
            msg_id = await sender.send_message(
                token,
                int(event["chat_id"]),
                event.get("reply_text") or " ",
                reply_markup=event.get("reply_markup"),
            )
            await postgres.mark_outbound_sent(pg_pool, int(event["id"]), telegram_message_id=msg_id)
            sent += 1
        except Exception as exc:
            await postgres.mark_outbound_failed(pg_pool, int(event["id"]), str(exc))
            logger.warning("outbox_send_failed", extra={"event_id": event.get("id"), "error": str(exc)})
    return sent


async def run_outbox_dispatcher(pg_pool, sender: TelegramSender = telegram_sender, interval: int = 15) -> None:
    while True:
        try:
            await dispatch_once(pg_pool, sender)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("outbox_dispatcher_error", extra={"error": str(exc)})
        await asyncio.sleep(interval)

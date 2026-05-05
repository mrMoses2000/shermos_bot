"""Retry loop for pending Telegram outbound events."""

from __future__ import annotations

import asyncio

from src.bot.errors import PermanentSendError
from src.bot.telegram_sender import TelegramSender, telegram_sender
from src.bot.whatsapp_sender import manager_whatsapp_sender, whatsapp_sender
from src.config import settings
from src.db import postgres
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def dispatch_once(pg_pool, sender: TelegramSender = telegram_sender) -> int:
    events = await postgres.get_pending_outbound(pg_pool, limit=20)
    sent = 0
    for event in events:
        channel = event.get("channel") or "telegram"
        if channel == "whatsapp" and event.get("external_message_id"):
            await postgres.mark_outbound_sent(
                pg_pool,
                int(event["id"]),
                external_message_id=str(event["external_message_id"]),
            )
            continue
        if channel != "whatsapp" and event.get("telegram_message_id"):
            await postgres.mark_outbound_sent(
                pg_pool,
                int(event["id"]),
                int(event["telegram_message_id"]),
            )
            continue
        if channel == "whatsapp":
            active_sender = manager_whatsapp_sender if event.get("bot_type") == "manager" else whatsapp_sender
            token = ""
            chat_id = event.get("external_chat_id") or event["chat_id"]
        else:
            active_sender = sender
            token = settings.manager_bot_token if event.get("bot_type") == "manager" else settings.telegram_bot_token
            chat_id = int(event["chat_id"])
        try:
            if channel == "whatsapp":
                msg_id = await active_sender.send_message(
                    token,
                    chat_id,
                    event.get("reply_text") or " ",
                    reply_markup=event.get("reply_markup"),
                    idempotency_key=event.get("idempotency_key"),
                )
                await postgres.mark_outbound_sent(
                    pg_pool,
                    int(event["id"]),
                    external_message_id=str(msg_id) if msg_id is not None else None,
                )
            else:
                msg_id = await active_sender.send_message(
                    token,
                    chat_id,
                    event.get("reply_text") or " ",
                    reply_markup=event.get("reply_markup"),
                )
                await postgres.mark_outbound_sent(pg_pool, int(event["id"]), telegram_message_id=msg_id)
            sent += 1
        except PermanentSendError as exc:
            await postgres.mark_outbound_dead(pg_pool, int(event["id"]), str(exc))
            logger.info("outbox_send_permanent_fail", extra={"event_id": event.get("id"), "error": str(exc)})
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

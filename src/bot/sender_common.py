"""Common logic for sending and recording outbound messages."""

from __future__ import annotations

from typing import Any
from uuid import uuid4
from src.config import settings
from src.db import postgres
from src.bot.whatsapp_sender import WhatsAppSender, whatsapp_sender, manager_whatsapp_sender
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def send_and_record(
    pg_pool,
    sender: WhatsAppSender,
    token: str,
    chat_id: int | str,
    text: str,
    bot_type: str = "client",
    reply_markup: dict | None = None,
    inbound_event_id: int | None = None,
    idempotency_key: str | None = None,
) -> int:
    """Send message and record it in outbound_events table."""
    channel = getattr(sender, "channel", "telegram")
    if channel == "whatsapp" and not idempotency_key:
        idempotency_key = str(uuid4())
    
    # Record as pending first.
    # Always store chat_id as an integer in the DB column so tests and queries
    # that filter by chat_id work for both telegram and whatsapp jobs.
    try:
        numeric_chat_id = int(chat_id)
    except (TypeError, ValueError):
        numeric_chat_id = 0
    event_id = await postgres.insert_outbound_event(
        pg_pool,
        numeric_chat_id,
        text,
        reply_markup=reply_markup,
        bot_type=bot_type,
        channel=channel,
        external_chat_id=str(chat_id) if channel == "whatsapp" else None,
        inbound_event_id=inbound_event_id,
        idempotency_key=idempotency_key,
    )

    try:
        if channel == "whatsapp":
            msg_id = await sender.send_message(
                token,
                chat_id,
                text,
                reply_markup=reply_markup,
                idempotency_key=idempotency_key,
            )
            await postgres.mark_outbound_sent(pg_pool, event_id, external_message_id=str(msg_id) if msg_id else None)
        else:
            msg_id = await sender.send_message(token, int(chat_id), text, reply_markup=reply_markup)
            await postgres.mark_outbound_sent(pg_pool, event_id, telegram_message_id=msg_id)
    except Exception as exc:
        await postgres.mark_outbound_failed(pg_pool, event_id, str(exc))
        logger.warning(
            "outbound_send_failed",
            extra={"event_id": event_id, "error": str(exc), "bot_type": bot_type, "channel": channel},
        )
        raise

    return event_id

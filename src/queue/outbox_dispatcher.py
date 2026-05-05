"""Retry loop for pending WhatsApp outbound events."""

from __future__ import annotations

import asyncio

from src.bot.errors import PermanentSendError
from src.bot.whatsapp_sender import manager_whatsapp_sender, whatsapp_sender
from src.config import settings
from src.db import postgres
from src.utils.logger import setup_logger
from src.utils.metrics import outbound_events_total

logger = setup_logger(__name__)


async def dispatch_once(pg_pool) -> int:
    events = await postgres.get_pending_outbound(pg_pool, limit=20)
    sent = 0
    for event in events:
        channel = event.get("channel") or "whatsapp"
        if channel == "whatsapp" and event.get("external_message_id"):
            await postgres.mark_outbound_sent(
                pg_pool,
                int(event["id"]),
                external_message_id=str(event["external_message_id"]),
            )
            continue
        if channel != "whatsapp":
            # Telegram events are no longer dispatched — mark as dead
            await postgres.mark_outbound_dead(pg_pool, int(event["id"]), "telegram_decommissioned")
            outbound_events_total.labels(channel=channel, status="dead").inc()
            continue
        active_sender = manager_whatsapp_sender if event.get("bot_type") == "manager" else whatsapp_sender
        token = ""
        chat_id = event.get("external_chat_id") or event["chat_id"]
        try:
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
            outbound_events_total.labels(channel=channel, status="sent").inc()
            sent += 1
        except PermanentSendError as exc:
            await postgres.mark_outbound_dead(pg_pool, int(event["id"]), str(exc))
            outbound_events_total.labels(channel=channel, status="dead").inc()
            logger.info("outbox_send_permanent_fail", extra={"event_id": event.get("id"), "error": str(exc)})
        except Exception as exc:
            await postgres.mark_outbound_failed(pg_pool, int(event["id"]), str(exc))
            outbound_events_total.labels(channel=channel, status="failed").inc()
            logger.warning("outbox_send_failed", extra={"event_id": event.get("id"), "error": str(exc)})
    return sent


async def run_outbox_dispatcher(pg_pool, interval: int = 15) -> None:
    while True:
        try:
            await dispatch_once(pg_pool)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("outbox_dispatcher_error", extra={"error": str(exc)})
        await asyncio.sleep(interval)

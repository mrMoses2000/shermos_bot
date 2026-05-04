"""Shared WhatsApp inbound adapter for aiohttp webhook and FastAPI API."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from src.config import settings
from src.db import postgres
from src.models import Job
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def is_bridge_secret_valid(incoming_secret: str | None) -> bool:
    expected = settings.bridge_shared_secret
    if not expected:
        return False
    return hmac.compare_digest(incoming_secret or "", expected)


def synthetic_update_id(channel: str, external_id: str) -> int:
    digest = hashlib.sha256(f"{channel}:{external_id}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    return value or 1


def _stable_bigint(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    stable = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    return stable or 1


def _phone_to_chat_id(phone_e164: str, fallback: str) -> int:
    digits = re.sub(r"\D+", "", phone_e164 or "")
    if digits:
        return int(digits)
    return _stable_bigint(fallback)


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _bridge_role(payload: dict[str, Any]) -> str:
    role = str(payload.get("bridge_role") or payload.get("bot_type") or "client").strip().lower()
    return "manager" if role == "manager" else "client"


def _is_allowed_manager_phone(phone_e164: str) -> bool:
    allowed = set(settings.manager_whatsapp_numbers_list)
    return bool(allowed) and _digits(phone_e164) in allowed


def _sender_phone(payload: dict[str, Any]) -> str:
    raw_key = (payload.get("raw") or {}).get("key") or {}
    sender_pn = str(raw_key.get("senderPn") or "")
    return sender_pn.split("@", 1)[0] if sender_pn else ""


def _derive_phone(payload: dict[str, Any]) -> str:
    sender_phone = _sender_phone(payload)
    phone = str(payload.get("phone_e164") or "")
    jid = str(payload.get("jid") or payload.get("external_chat_id") or "")
    jid_user = jid.split("@", 1)[0] if jid else ""
    # If WhatsApp delivered an LID remoteJid, prefer senderPn even when the
    # bridge payload still carries the older, incorrect phone_e164 form.
    if sender_phone and (jid.endswith("@lid") or not phone or phone == jid_user):
        return sender_phone
    if phone:
        return phone
    if sender_phone:
        return sender_phone
    return jid.split("@", 1)[0] if jid else ""


def _derive_external_chat_id(payload: dict[str, Any], phone_e164: str) -> str:
    if phone_e164:
        return f"{phone_e164}@s.whatsapp.net"
    return str(payload.get("external_chat_id") or payload.get("jid") or "")


def _normalize_message(payload: dict[str, Any]) -> tuple[str, str, str]:
    text = str(payload.get("text") or "")
    raw_msg_type = str(payload.get("msg_type") or "text")
    callback_data = str(payload.get("callback_data") or "")

    if callback_data:
        return text, "callback_query", callback_data
    if text.startswith("/"):
        return text, "command", ""
    if raw_msg_type in {"image", "document", "voice"} and not text:
        labels = {
            "image": "изображение",
            "document": "документ",
            "voice": "голосовое сообщение",
        }
        text = f"Пользователь отправил в WhatsApp {labels.get(raw_msg_type, 'медиа')}."
    return text, raw_msg_type, ""


def _raw_update(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        json.dumps(payload)
        return payload
    except TypeError:
        return {"raw": str(payload)}


async def enqueue_whatsapp_inbound(pg_pool, redis_client, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = str(payload.get("external_id") or "")
    if not external_id:
        raise ValueError("external_id is required")

    phone_e164 = _derive_phone(payload)
    external_chat_id = _derive_external_chat_id(payload, phone_e164)
    if not external_chat_id:
        raise ValueError("external_chat_id is required")

    update_id = synthetic_update_id("whatsapp", external_id)
    chat_id = _phone_to_chat_id(phone_e164, external_chat_id)
    text, msg_type, callback_data = _normalize_message(payload)
    bridge_role = _bridge_role(payload)
    sender_is_staff = _is_allowed_manager_phone(phone_e164)
    # bridge_role = channel (which WA number received it); bot_type = sender role
    bot_type = "manager" if sender_is_staff else "client"
    queue_name = "queue:manager" if bot_type == "manager" else "queue:incoming"
    if bridge_role == "manager" and not sender_is_staff:
        # Client wrote to manager WA number — normal, goes to client queue
        logger.info("whatsapp_client_on_manager_number", extra={"phone_e164": phone_e164})

    is_new = await postgres.mark_external_update_received(
        pg_pool,
        "whatsapp",
        external_id,
        update_id,
    )
    if not is_new:
        return {"queued": False, "duplicate": True, "update_id": update_id}

    await postgres.insert_inbound_event(
        pg_pool,
        update_id,
        chat_id,
        chat_id,
        text,
        _raw_update(payload),
        channel="whatsapp",
        external_message_id=external_id,
        external_chat_id=external_chat_id,
        phone_e164=phone_e164,
        media_path=payload.get("media_path"),
        media_mime=payload.get("media_mime"),
    )

    job = Job(
        channel="whatsapp",
        update_id=update_id,
        chat_id=chat_id,
        user_id=chat_id,
        text=text,
        msg_type=msg_type,
        callback_data=callback_data,
        external_chat_id=external_chat_id,
        external_message_id=external_id,
        phone_e164=phone_e164,
        media_path=payload.get("media_path"),
        media_mime=payload.get("media_mime"),
        raw_update=_raw_update(payload),
        bot_type=bot_type,
        bridge_role=bridge_role,
    )
    await redis_client.enqueue_job(queue_name, job)
    logger.info(
        "whatsapp_inbound_queued",
        extra={
            "external_id": external_id,
            "chat_id": chat_id,
            "update_id": update_id,
            "bot_type": bot_type,
            "queue": queue_name,
        },
    )
    return {"queued": True, "duplicate": False, "update_id": update_id}

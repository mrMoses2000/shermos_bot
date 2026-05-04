"""aiohttp webhook handlers for Telegram bots and internal WhatsApp ingress."""

from __future__ import annotations

from aiohttp import web

from src.config import settings
from src.bot.whatsapp_ingress import enqueue_whatsapp_inbound, is_bridge_secret_valid
from src.db import postgres
from src.llm.health_check import is_gemini_healthy
from src.models import Job
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _extract_update(update: dict) -> tuple[int, int, str, str, str]:
    message = update.get("message") or update.get("edited_message") or {}
    callback = update.get("callback_query") or {}
    if callback:
        cb_message = callback.get("message") or {}
        chat = cb_message.get("chat") or {}
        user = callback.get("from") or {}
        return (
            int(chat.get("id", user.get("id", 0))),
            int(user.get("id", chat.get("id", 0))),
            callback.get("data", ""),
            "callback_query",
            callback.get("data", ""),
        )

    chat = message.get("chat") or {}
    user = message.get("from") or {}
    text = message.get("text") or message.get("caption") or ""
    if text.startswith("/"):
        msg_type = "command"
    elif "voice" in message:
        msg_type = "voice"
    elif "photo" in message:
        msg_type = "photo"
    else:
        msg_type = "text"
    return (
        int(chat.get("id", 0)),
        int(user.get("id", chat.get("id", 0))),
        text,
        msg_type,
        "",
    )


async def _process_webhook(request: web.Request, bot_type: str, secret_token: str) -> web.Response:
    try:
        incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming_secret != secret_token:
            logger.warning("webhook_secret_mismatch", extra={"bot_type": bot_type})
            return web.json_response({"ok": True})

        update = await request.json()
        update_id = int(update.get("update_id", 0))
        
        # Negate update_id for manager bot to avoid collisions with client bot
        if bot_type == "manager" and update_id > 0:
            update_id = -update_id

        chat_id, user_id, text, msg_type, callback_data = _extract_update(update)
        if not update_id or not chat_id:
            logger.warning("webhook_missing_update_fields", extra={"bot_type": bot_type})
            return web.json_response({"ok": True})

        pg_pool = request.app["pg_pool"]
        redis_client = request.app["redis"]
        is_new = await postgres.mark_update_received(pg_pool, update_id)
        if not is_new:
            return web.json_response({"ok": True, "duplicate": True})

        await postgres.insert_inbound_event(pg_pool, update_id, chat_id, user_id, text, update)
        job = Job(
            update_id=update_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            callback_data=callback_data,
            raw_update=update,
            bot_type=bot_type,
        )
        queue_name = "queue:manager" if bot_type == "manager" else "queue:incoming"
        await redis_client.enqueue_job(queue_name, job)
    except Exception as exc:
        logger.exception("webhook_processing_error", extra={"bot_type": bot_type, "error": str(exc)})
    return web.json_response({"ok": True})


async def handle_client_webhook(request: web.Request) -> web.Response:
    return await _process_webhook(request, "client", settings.telegram_webhook_secret)


async def handle_manager_webhook(request: web.Request) -> web.Response:
    return await _process_webhook(request, "manager", settings.manager_webhook_secret)


async def handle_whatsapp_inbound(request: web.Request) -> web.Response:
    if not is_bridge_secret_valid(request.headers.get("X-Bridge-Secret")):
        logger.warning("whatsapp_ingress_secret_mismatch")
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    try:
        payload = await request.json()
        result = await enqueue_whatsapp_inbound(request.app["pg_pool"], request.app["redis"], payload)
        return web.json_response({"ok": True, **result})
    except PermissionError as exc:
        logger.warning("whatsapp_ingress_forbidden", extra={"error": str(exc)})
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    except Exception as exc:
        logger.exception("whatsapp_ingress_error", extra={"error": str(exc)})
        return web.json_response({"ok": False, "error": "ingress_failed"}, status=500)


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "service": "shermos-webhook",
            "gemini_healthy": is_gemini_healthy(),
        }
    )


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/health", health)
    app.router.add_post(settings.webhook_path_client, handle_client_webhook)
    app.router.add_post(settings.webhook_path_manager, handle_manager_webhook)
    app.router.add_post("/internal/whatsapp/inbound", handle_whatsapp_inbound)

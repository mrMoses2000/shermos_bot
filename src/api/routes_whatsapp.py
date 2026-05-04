"""Internal WhatsApp ingress route used by whatsapp-bridge."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.bot.whatsapp_ingress import enqueue_whatsapp_inbound, is_bridge_secret_valid
from src.config import settings
from src.db.redis_client import RedisClient
from src.utils.logger import setup_logger

router = APIRouter()
logger = setup_logger(__name__)


async def _get_redis_client(request: Request) -> RedisClient:
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is None:
        redis_client = RedisClient(settings.redis_url)
        await redis_client.connect()
        request.app.state.redis_client = redis_client
    return redis_client


@router.post("/internal/whatsapp/inbound")
async def whatsapp_inbound(request: Request) -> dict:
    if not is_bridge_secret_valid(request.headers.get("x-bridge-secret")):
        logger.warning("whatsapp_ingress_secret_mismatch")
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        payload = await request.json()
        redis_client = await _get_redis_client(request)
        result = await enqueue_whatsapp_inbound(
            request.app.state.pg_pool,
            redis_client,
            payload,
        )
        return {"ok": True, **result}
    except HTTPException:
        raise
    except PermissionError as exc:
        logger.warning("whatsapp_ingress_forbidden", extra={"error": str(exc)})
        raise HTTPException(status_code=403, detail="forbidden") from exc
    except Exception as exc:
        logger.exception("whatsapp_ingress_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="ingress_failed") from exc

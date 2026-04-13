"""Settings API routes."""

from fastapi import APIRouter, Depends

from src.api.auth import require_telegram_auth
from src.config import settings
from src.utils.config_manager import config

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_telegram_auth)])


@router.get("")
async def get_settings():
    return {
        "mini_app_url": settings.mini_app_url,
        "webhook_url_client": settings.webhook_url_client,
        "webhook_url_manager": settings.webhook_url_manager,
        "materials": config.get_section("materials"),
        "constraints": config.get_section("constraints"),
    }

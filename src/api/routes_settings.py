"""Settings API routes."""

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.config import settings
from src.utils.config_manager import config

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_settings():
    return {
        "mini_app_url": settings.mini_app_url,
        "materials": config.get_section("materials"),
        "constraints": config.get_section("constraints"),
    }

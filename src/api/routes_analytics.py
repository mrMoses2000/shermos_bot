"""Analytics API routes."""

from fastapi import APIRouter, Depends, Query

from src.api.auth import require_telegram_auth
from src.api.deps import get_pool
from src.db import postgres

router = APIRouter(prefix="/api/analytics", tags=["analytics"], dependencies=[Depends(require_telegram_auth)])


@router.get("/dashboard")
async def dashboard(days: int = Query(default=30, ge=1, le=365), pool=Depends(get_pool)):
    return await postgres.get_dashboard_stats(pool, days=days)

"""Measurement API routes."""

from fastapi import APIRouter, Depends, Query

from src.api.auth import require_telegram_auth
from src.api.deps import get_pool
from src.db import postgres

router = APIRouter(
    prefix="/api/measurements",
    tags=["measurements"],
    dependencies=[Depends(require_telegram_auth)],
)


@router.get("")
async def list_measurements(
    upcoming_only: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    pool=Depends(get_pool),
):
    return {"items": await postgres.list_measurements(pool, upcoming_only=upcoming_only, limit=limit)}


@router.post("/{measurement_id}/confirm")
async def confirm_measurement(measurement_id: int, pool=Depends(get_pool)):
    return await postgres.confirm_measurement(pool, measurement_id)


@router.get("/client/{chat_id}")
async def client_measurements(chat_id: int, pool=Depends(get_pool)):
    return {"items": await postgres.get_measurements_for_client(pool, chat_id)}

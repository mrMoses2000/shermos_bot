"""Measurement API routes for Mini App CMS."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth import require_telegram_auth
from src.api.deps import get_pool
from src.config import settings
from src.db import postgres
from src.engine.measurement_service import (
    get_available_slots,
    get_measurements_for_date,
    update_measurement_status,
)

router = APIRouter(
    prefix="/api/measurements",
    tags=["measurements"],
    dependencies=[Depends(require_telegram_auth)],
)


@router.get("")
async def list_measurements(
    upcoming_only: bool = True,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    pool=Depends(get_pool),
):
    """List measurements with optional filters."""
    items = await postgres.list_measurements(pool, upcoming_only=upcoming_only, limit=limit)
    if status:
        items = [m for m in items if m.get("status") == status]
    return {"items": items}


@router.get("/date/{date}")
async def measurements_by_date(date: str, pool=Depends(get_pool)):
    """Get all measurements for a specific date (calendar day view)."""
    return {"items": await get_measurements_for_date(pool, date, settings.timezone)}


@router.get("/slots/{date}")
async def available_slots(date: str, pool=Depends(get_pool)):
    """Get available time slots for a specific date."""
    slots = await get_available_slots(pool, date, settings.timezone)
    return {"date": date, "slots": slots}


@router.get("/client/{chat_id}")
async def client_measurements(chat_id: int, pool=Depends(get_pool)):
    """Get all measurements for a specific client."""
    return {"items": await postgres.get_measurements_for_client(pool, chat_id)}


class StatusUpdate(BaseModel):
    status: str
    reason: str = ""


@router.patch("/{measurement_id}/status")
async def change_measurement_status(
    measurement_id: int,
    body: StatusUpdate,
    pool=Depends(get_pool),
):
    """Change measurement status (confirm, reject, cancel, complete)."""
    try:
        result = await update_measurement_status(
            pool, measurement_id, body.status, reason=body.reason
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{measurement_id}/confirm")
async def confirm_measurement(measurement_id: int, pool=Depends(get_pool)):
    """Shortcut to confirm a measurement."""
    try:
        return await update_measurement_status(pool, measurement_id, "confirmed")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{measurement_id}/complete")
async def complete_measurement(measurement_id: int, pool=Depends(get_pool)):
    """Mark measurement as completed (after the visit)."""
    try:
        return await update_measurement_status(pool, measurement_id, "completed")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

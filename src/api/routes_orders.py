"""Order API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth import require_telegram_auth
from src.api.deps import get_pool
from src.db import postgres

router = APIRouter(prefix="/api/orders", tags=["orders"], dependencies=[Depends(require_telegram_auth)])


class OrderStatusPatch(BaseModel):
    status: str
    note: str = ""


@router.get("")
async def list_orders(
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    pool=Depends(get_pool),
):
    return {"items": await postgres.list_orders(pool, status=status, search=search, limit=limit, offset=offset)}


@router.get("/{request_id}")
async def get_order(request_id: str, pool=Depends(get_pool)):
    order = await postgres.get_order(pool, request_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/{request_id}/status")
async def update_status(request_id: str, patch: OrderStatusPatch, pool=Depends(get_pool)):
    return await postgres.update_order_status(pool, request_id, patch.status, patch.note)

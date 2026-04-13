"""Client API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth import require_telegram_auth
from src.api.deps import get_pool
from src.db import postgres

router = APIRouter(prefix="/api/clients", tags=["clients"], dependencies=[Depends(require_telegram_auth)])


class ClientPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None


@router.get("")
async def list_clients(
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    pool=Depends(get_pool),
):
    return {"items": await postgres.list_clients(pool, search=search, limit=limit, offset=offset)}


@router.get("/{chat_id}")
async def get_client(chat_id: int, pool=Depends(get_pool)):
    client = await postgres.get_client_with_orders(pool, chat_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.patch("/{chat_id}")
async def update_client(chat_id: int, patch: ClientPatch, pool=Depends(get_pool)):
    return await postgres.update_client(pool, chat_id, **patch.model_dump(exclude_none=True))

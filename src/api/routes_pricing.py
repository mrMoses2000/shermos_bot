"""Pricing and material API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.auth import require_telegram_auth
from src.api.deps import get_pool
from src.db import postgres
from src.engine.pricing_cache import pricing_cache

router = APIRouter(prefix="/api/pricing", tags=["pricing"], dependencies=[Depends(require_telegram_auth)])


class PricePatch(BaseModel):
    name: str | None = None
    category: str | None = None
    amount: float | None = None
    currency: str | None = None
    metadata: dict | None = None


class MaterialPatch(BaseModel):
    kind: str | None = None
    name: str | None = None
    color: list[float] | None = None
    roughness: float | None = None
    price_modifier: float | None = None
    metadata: dict | None = None


@router.get("/prices")
async def get_prices(pool=Depends(get_pool)):
    return {"items": await postgres.get_prices(pool)}


@router.patch("/prices/{price_id}")
async def update_price(price_id: str, patch: PricePatch, pool=Depends(get_pool)):
    result = await postgres.update_price(pool, price_id, **patch.model_dump(exclude_none=True))
    pricing_cache._loaded_at = 0
    return result


@router.get("/materials")
async def get_materials(pool=Depends(get_pool)):
    return {"items": await postgres.get_materials(pool)}


@router.patch("/materials/{material_id}")
async def update_material(material_id: str, patch: MaterialPatch, pool=Depends(get_pool)):
    result = await postgres.update_material(pool, material_id, **patch.model_dump(exclude_none=True))
    pricing_cache._loaded_at = 0
    return result

"""Pricing and material API routes (incl. master-CMS lifecycle)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.deps import get_pool
from src.db import postgres
from src.engine.pricing_cache import pricing_cache

router = APIRouter(prefix="/api/pricing", tags=["pricing"], dependencies=[Depends(require_auth)])


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


class MaterialActiveBody(BaseModel):
    is_active: bool


class MaterialCreate(BaseModel):
    kind: str = Field(min_length=1)
    name: str = Field(min_length=1)
    color: list[float] | None = None
    roughness: float | None = None
    price_modifier: float | None = None
    metadata: dict | None = None


class CodegenResolveBody(BaseModel):
    status: str = "merged"  # merged | cancelled
    commit_sha: str | None = None


def _actor_phone(request: Request) -> str | None:
    """JWT auth puts the manager phone into request.state.user (see api/auth.py)."""
    user = getattr(request.state, "user", None)
    if not user:
        return None
    if isinstance(user, dict):
        return user.get("phone")
    return getattr(user, "phone", None)


@router.get("/prices")
async def get_prices(pool=Depends(get_pool)):
    return {"items": await postgres.get_prices(pool)}


@router.patch("/prices/{price_id}")
async def update_price(price_id: str, patch: PricePatch, pool=Depends(get_pool)):
    result = await postgres.update_price(pool, price_id, **patch.model_dump(exclude_none=True))
    pricing_cache._loaded_at = 0
    return result


@router.get("/materials")
async def get_materials(
    pool=Depends(get_pool),
    include_inactive: bool = Query(False, alias="include_inactive"),
    kind: str | None = Query(None),
):
    return {
        "items": await postgres.get_materials(
            pool, include_inactive=include_inactive, kind=kind
        )
    }


@router.get("/materials/search")
async def search_materials(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    pool=Depends(get_pool),
):
    return {"items": await postgres.search_materials(pool, q, limit=limit)}


@router.post("/materials")
async def create_material(body: MaterialCreate, request: Request, pool=Depends(get_pool)):
    """Create a new material from the CMS.

    If a row with the same canonical_key already exists, it is restored
    (`{"_restored": true}` in the response) instead of being duplicated.
    Otherwise the row is created with `pending_codegen=true` and a
    codegen_task is queued.
    """
    try:
        result = await postgres.create_material_with_codegen(
            pool,
            kind=body.kind,
            name=body.name,
            color=body.color,
            roughness=body.roughness,
            price_modifier=body.price_modifier,
            metadata=body.metadata,
            actor_phone=_actor_phone(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    pricing_cache._loaded_at = 0
    return result


@router.patch("/materials/{material_id}")
async def update_material(material_id: str, patch: MaterialPatch, pool=Depends(get_pool)):
    result = await postgres.update_material(pool, material_id, **patch.model_dump(exclude_none=True))
    pricing_cache._loaded_at = 0
    return result


@router.post("/materials/{material_id}/active")
async def set_material_active(
    material_id: str,
    body: MaterialActiveBody,
    request: Request,
    pool=Depends(get_pool),
):
    try:
        result = await postgres.set_material_active(
            pool,
            material_id,
            body.is_active,
            actor_phone=_actor_phone(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    pricing_cache._loaded_at = 0
    return result


@router.get("/codegen/tasks")
async def list_codegen_tasks(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    pool=Depends(get_pool),
):
    return {"items": await postgres.list_codegen_tasks(pool, status=status, limit=limit)}


@router.post("/codegen/tasks/{task_id}/dispatch")
async def dispatch_codegen_task(task_id: int, pool=Depends(get_pool)):
    """Generate the prompt text for this task and mark it as `prompt_issued`.

    Master-bot calls this from /codegen_dispatch; CMS UI exposes a button
    that hits the same endpoint and shows the prompt in a modal.
    """
    from src.utils.codegen_prompt import build_codegen_prompt

    tasks = await postgres.list_codegen_tasks(pool, limit=200)
    target = next((t for t in tasks if t["id"] == task_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Codegen task not found")
    prompt = build_codegen_prompt(target)
    updated = await postgres.mark_codegen_task(
        pool, task_id, status="prompt_issued", prompt_text=prompt
    )
    return {"task": updated, "prompt": prompt}


@router.post("/codegen/tasks/{task_id}/resolve")
async def resolve_codegen_task(
    task_id: int,
    body: CodegenResolveBody,
    pool=Depends(get_pool),
):
    """Master closes a task: status='merged' once the codegen PR is merged."""
    if body.status not in {"merged", "cancelled"}:
        raise HTTPException(status_code=400, detail="status must be merged|cancelled")
    updated = await postgres.mark_codegen_task(
        pool, task_id, status=body.status, commit_sha=body.commit_sha
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Codegen task not found")
    return updated

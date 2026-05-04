"""Bridge healthcheck aggregation route. Used by CMS Status page."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.config import settings

router = APIRouter(tags=["health"])

_TIMEOUT = aiohttp.ClientTimeout(total=3)


async def _fetch_bridge(session: aiohttp.ClientSession, url: str, role: str) -> dict[str, Any]:
    """Fetch /healthz from a single bridge, returning a normalised dict."""
    try:
        async with session.get(url, timeout=_TIMEOUT) as resp:
            if resp.status >= 400:
                return {"connected": False, "role": role, "error": f"http_{resp.status}"}
            data: dict[str, Any] = await resp.json(content_type=None)
            # Merge in expected role so callers always have it even if bridge omits it.
            data.setdefault("role", role)
            return data
    except asyncio.TimeoutError:
        return {"connected": False, "role": role, "error": "timeout"}
    except aiohttp.ClientConnectorError as exc:
        return {"connected": False, "role": role, "error": f"connection_refused: {exc.strerror}"}
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "role": role, "error": str(exc)}


@router.get("/api/health/bridges")
async def health_bridges(
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    """Aggregate /healthz from both WhatsApp bridges. Used by CMS Status page."""

    client_url = settings.whatsapp_bridge_url.rstrip("/") + "/healthz"
    manager_url_raw = settings.manager_whatsapp_bridge_url.strip()

    pool = request.app.state.pg_pool
    outbox_pending: int = await pool.fetchval(
        "SELECT count(*) FROM outbound_events WHERE status='pending'"
    )

    async with aiohttp.ClientSession() as session:
        if manager_url_raw:
            manager_url = manager_url_raw.rstrip("/") + "/healthz"
            client_result, manager_result = await asyncio.gather(
                _fetch_bridge(session, client_url, "client"),
                _fetch_bridge(session, manager_url, "manager"),
            )
        else:
            client_result = await _fetch_bridge(session, client_url, "client")
            manager_result = {"configured": False}

    return {
        "client": client_result,
        "manager": manager_result,
        "outbox": {"pending": outbox_pending},
    }

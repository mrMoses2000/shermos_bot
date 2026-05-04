"""Tests for /api/health/bridges endpoint (Phase 1.5.5)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import get_pool
from tests.helpers import FakePool, signed_init_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    return {"X-Telegram-Init-Data": signed_init_data()}


def _make_fake_response(data: dict[str, Any], status: int = 200) -> MagicMock:
    """Return a mock aiohttp response context-manager that yields JSON."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    # Context manager protocol
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_error_response(exc: Exception) -> MagicMock:
    """Return a mock that raises *exc* on __aenter__."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(side_effect=exc)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _build_client(pool: FakePool) -> TestClient:
    app = create_app()
    app.state.pg_pool = pool
    app.dependency_overrides[get_pool] = lambda: pool
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1 – both bridges healthy
# ---------------------------------------------------------------------------


def test_both_bridges_healthy(monkeypatch):
    monkeypatch.setattr("src.api.routes_health.settings.whatsapp_bridge_url", "http://client-bridge")
    monkeypatch.setattr("src.api.routes_health.settings.manager_whatsapp_bridge_url", "http://manager-bridge")

    client_data = {"connected": True, "role": "client", "last_message_at": "2026-05-04T10:00:00Z", "reconnect_attempts": 0}
    manager_data = {"connected": True, "role": "manager", "last_message_at": "2026-05-04T09:00:00Z", "reconnect_attempts": 1}

    pool = FakePool(results=[5])  # outbox pending count

    session_mock = MagicMock()
    session_mock.get.side_effect = [
        _make_fake_response(client_data),
        _make_fake_response(manager_data),
    ]
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session_mock)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("src.api.routes_health.aiohttp.ClientSession", return_value=session_cm):
        response = _build_client(pool).get("/api/health/bridges", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["client"]["connected"] is True
    assert body["client"]["role"] == "client"
    assert body["manager"]["connected"] is True
    assert body["manager"]["role"] == "manager"
    assert body["outbox"]["pending"] == 5


# ---------------------------------------------------------------------------
# Test 2 – manager bridge unreachable (ConnectionError)
# ---------------------------------------------------------------------------


def test_manager_bridge_unreachable(monkeypatch):
    import aiohttp as _aiohttp

    monkeypatch.setattr("src.api.routes_health.settings.whatsapp_bridge_url", "http://client-bridge")
    monkeypatch.setattr("src.api.routes_health.settings.manager_whatsapp_bridge_url", "http://manager-bridge")

    client_data = {"connected": True, "role": "client", "last_message_at": "2026-05-04T10:00:00Z", "reconnect_attempts": 0}

    # Build a fake ClientConnectorError (needs os_error positional arg)
    import os
    conn_err = _aiohttp.ClientConnectorError.__new__(_aiohttp.ClientConnectorError)
    OSError.__init__(conn_err, "Connection refused")
    conn_err.strerror = "Connection refused"

    pool = FakePool(results=[0])

    session_mock = MagicMock()
    session_mock.get.side_effect = [
        _make_fake_response(client_data),
        _make_error_response(conn_err),
    ]
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session_mock)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("src.api.routes_health.aiohttp.ClientSession", return_value=session_cm):
        response = _build_client(pool).get("/api/health/bridges", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["client"]["connected"] is True
    assert body["manager"]["connected"] is False
    assert "error" in body["manager"]


# ---------------------------------------------------------------------------
# Test 3 – manager bridge URL empty → {"configured": false}
# ---------------------------------------------------------------------------


def test_manager_bridge_not_configured(monkeypatch):
    monkeypatch.setattr("src.api.routes_health.settings.whatsapp_bridge_url", "http://client-bridge")
    monkeypatch.setattr("src.api.routes_health.settings.manager_whatsapp_bridge_url", "")

    client_data = {"connected": True, "role": "client", "last_message_at": "2026-05-04T10:00:00Z", "reconnect_attempts": 0}

    pool = FakePool(results=[0])

    session_mock = MagicMock()
    session_mock.get.return_value = _make_fake_response(client_data)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session_mock)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("src.api.routes_health.aiohttp.ClientSession", return_value=session_cm):
        response = _build_client(pool).get("/api/health/bridges", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["manager"] == {"configured": False}
    # Only one .get() call should have been made (client bridge only)
    assert session_mock.get.call_count == 1


# ---------------------------------------------------------------------------
# Test 4 – no auth header → 401
# ---------------------------------------------------------------------------


def test_no_auth_returns_401():
    pool = FakePool(results=[0])
    response = _build_client(pool).get("/api/health/bridges")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 5 – outbox pending count is actually queried (mock fetchval)
# ---------------------------------------------------------------------------


def test_outbox_pending_count_queried(monkeypatch):
    monkeypatch.setattr("src.api.routes_health.settings.whatsapp_bridge_url", "http://client-bridge")
    monkeypatch.setattr("src.api.routes_health.settings.manager_whatsapp_bridge_url", "")

    client_data = {"connected": True, "role": "client", "last_message_at": None, "reconnect_attempts": 0}

    # FakePool with explicit outbox count
    pool = FakePool(results=[42])

    session_mock = MagicMock()
    session_mock.get.return_value = _make_fake_response(client_data)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session_mock)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("src.api.routes_health.aiohttp.ClientSession", return_value=session_cm):
        response = _build_client(pool).get("/api/health/bridges", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["outbox"]["pending"] == 42

    # Verify fetchval was actually called with the right query fragment
    assert len(pool.calls) == 1
    method, query, _args = pool.calls[0]
    assert method == "fetchval"
    assert "outbound_events" in query
    assert "pending" in query

"""Tests for CORS middleware configuration (step 3.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app


class FakePool:
    async def fetchrow(self, query, *args):
        return None

    async def fetchval(self, query, *args):
        return 1

    async def execute(self, query, *args):
        return "OK"


def make_client(monkeypatch, cors_origins: str) -> TestClient:
    """Create a TestClient with the given CORS_ALLOWED_ORIGINS setting."""
    import src.config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "cors_allowed_origins", cors_origins)
    app = create_app()
    app.state.pg_pool = FakePool()
    return TestClient(app, raise_server_exceptions=False)


def test_cors_blocked_when_empty_allowlist(monkeypatch):
    """With cors_allowed_origins='', evil.com should NOT receive ACAO header."""
    client = make_client(monkeypatch, "")
    response = client.options(
        "/api/orders",
        headers={
            "Origin": "https://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Either no ACAO header or it is not the evil origin
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao != "https://evil.com", (
        f"Expected ACAO to NOT be 'https://evil.com', but got: '{acao}'"
    )


def test_cors_allowed_for_explicit_origin(monkeypatch):
    """With cors_allowed_origins='https://cms.shermos.example', that origin gets ACAO."""
    client = make_client(monkeypatch, "https://cms.shermos.example")
    response = client.options(
        "/api/orders",
        headers={
            "Origin": "https://cms.shermos.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao == "https://cms.shermos.example", (
        f"Expected ACAO='https://cms.shermos.example', got: '{acao}'"
    )


def test_cors_second_origin_not_allowed_when_not_listed(monkeypatch):
    """With only one origin listed, a different origin is NOT granted ACAO."""
    client = make_client(monkeypatch, "https://cms.shermos.example")
    response = client.options(
        "/api/orders",
        headers={
            "Origin": "https://other.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao != "https://other.example.com", (
        f"Expected ACAO to NOT be 'https://other.example.com', got: '{acao}'"
    )


def test_cors_multiple_origins_allowed(monkeypatch):
    """With two origins in allowlist, both receive ACAO header."""
    client = make_client(monkeypatch, "https://cms.shermos.example,https://t.me")
    for origin in ["https://cms.shermos.example", "https://t.me"]:
        response = client.options(
            "/api/orders",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        acao = response.headers.get("access-control-allow-origin", "")
        assert acao == origin, f"Expected ACAO='{origin}', got: '{acao}'"


def test_cors_allowed_origins_list_property():
    """cors_allowed_origins_list splits correctly and strips whitespace."""
    from src.config import Settings

    s = Settings.model_construct(cors_allowed_origins="  https://a.com , https://b.com ")
    result = s.cors_allowed_origins_list
    assert result == ["https://a.com", "https://b.com"]


def test_cors_allowed_origins_list_empty():
    """Empty cors_allowed_origins yields empty list."""
    from src.config import Settings

    s = Settings.model_construct(cors_allowed_origins="")
    assert s.cors_allowed_origins_list == []

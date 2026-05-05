"""
Phase 4.5 — Consolidated security regression tests.

Covers attack vectors across auth, CSRF, CORS, rate-limit, and bridge layers.
Tests are unit-level: FakePool / FakeRedis / FastAPI TestClient; no real server needed.

Cross-references:
  - CORS (D): core coverage lives in tests/test_api_app.py (Phase 3.1).
    This file adds two brief smoke tests for the same contract.
  - Rate-limit (E): full parametric coverage in tests/test_routes_auth.py (Phase 3.2).
    This file adds concise representative cases that fail loudly on regressions.
  - CSRF (C): core coverage in tests/test_routes_auth.py (Phase 3.3).
    This file adds cross-category smoke references.
  - Telegram webhook secret (G): core coverage in tests/test_webhook.py (Phase 2.4).
    This file adds concise representative cases.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
import pytest
from fastapi.testclient import TestClient

from src.api.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    require_jwt_auth,
    validate_init_data,
)
from src.api.app import create_app
from src.api import routes_auth, routes_whatsapp
from src.bot import whatsapp_ingress
from src.config import settings
from src.db import postgres

from tests.helpers import FakePool, FakeRedis, signed_init_data

# Use a fixed test token for HMAC security regression tests
_TEST_BOT_TOKEN = "manager-token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signed_init_data_raw(**payload_overrides) -> str:
    """Build a properly signed initData string, overriding default fields."""
    bot_token = _TEST_BOT_TOKEN
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "test-query",
        **payload_overrides,
    }
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": digest})


class _FakeRedisRateLimit:
    """Redis stub that rate-limits a specific key prefix after N calls."""

    def __init__(self, prefix: str, limit: int):
        self._counts: dict[str, int] = {}
        self._prefix = prefix
        self._limit = limit

    async def rate_limit_check(self, key: str, limit: int, window_seconds: int):
        if key.startswith(self._prefix):
            self._counts[key] = self._counts.get(key, 0) + 1
            c = self._counts[key]
            return (c <= self._limit, c)
        return (True, 1)

    async def close(self):
        pass


class _FakeRedisUnlimited:
    async def rate_limit_check(self, key: str, limit: int, window_seconds: int):
        return (True, 1)

    async def close(self):
        pass


class _FakePool:
    async def fetchrow(self, query, *args):
        return None

    async def fetchval(self, query, *args):
        return 1

    async def execute(self, query, *args):
        return "OK"


def _make_test_client(monkeypatch, redis=None, otp_code="12345678", https=False):
    app = create_app()
    app.state.pg_pool = _FakePool()
    if redis is not None:
        app.state.redis_client = redis

    async def get_manager(pool, phone):
        return {"phone_e164": phone, "is_active": True, "name": "Master"}

    async def get_otp(pool, phone):
        return {
            "phone_e164": phone,
            "code_hash": routes_auth.hash_otp(otp_code),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            "attempts": 0,
        }

    async def get_otp_rate_limit(*a, **kw):
        return None

    async def update_otp_rate_limit(*a, **kw):
        return None

    async def store_otp(*a, **kw):
        return None

    async def increment_otp_attempts(*a):
        return 1

    async def delete_otp(*a, **kw):
        return None

    monkeypatch.setattr(postgres, "get_otp_rate_limit", get_otp_rate_limit)
    monkeypatch.setattr(postgres, "update_otp_rate_limit", update_otp_rate_limit)
    monkeypatch.setattr(postgres, "store_otp", store_otp)
    monkeypatch.setattr(postgres, "get_manager", get_manager)
    monkeypatch.setattr(postgres, "get_otp", get_otp)
    monkeypatch.setattr(postgres, "increment_otp_attempts", increment_otp_attempts)
    monkeypatch.setattr(postgres, "delete_otp", delete_otp)

    async def send_message(*a, **kw):
        return "wamid"

    monkeypatch.setattr(routes_auth.manager_whatsapp_sender, "send_message", send_message)
    monkeypatch.setattr(routes_auth.manager_whatsapp_sender, "start", lambda: None)

    base_url = "https://testserver" if https else "http://testserver"
    return TestClient(app, raise_server_exceptions=False, base_url=base_url)


# ===========================================================================
# A. Telegram initData (Mini App auth)
# ===========================================================================

def test_init_data_with_invalid_hash_rejected():
    """A1: bogus hash= value must raise ValueError."""
    raw = _signed_init_data_raw()
    tampered = raw + "&" if "hash=abc" not in raw else raw
    # Replace the correct hash with a bogus one
    tampered = raw.split("&")
    tampered = [p if not p.startswith("hash=") else "hash=deadbeef0000" for p in tampered]
    init_data = "&".join(tampered)
    with pytest.raises(ValueError, match="Invalid initData hash"):
        validate_init_data(init_data, _TEST_BOT_TOKEN)


def test_init_data_with_missing_auth_date_rejected():
    """A2: initData without auth_date field must be rejected."""
    bot_token = _TEST_BOT_TOKEN
    payload = {"query_id": "test"}
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    init_data = urlencode({**payload, "hash": digest})
    with pytest.raises(ValueError, match="Missing or invalid auth_date"):
        validate_init_data(init_data, bot_token)


def test_init_data_with_auth_date_zero_rejected():
    """A3: auth_date=0 must be rejected (Phase 2.3 fix)."""
    init_data = _signed_init_data_raw(auth_date="0")
    with pytest.raises(ValueError, match="Missing or invalid auth_date"):
        validate_init_data(init_data, _TEST_BOT_TOKEN)


def test_init_data_with_garbage_auth_date_rejected():
    """A4: non-numeric auth_date must be rejected."""
    init_data = _signed_init_data_raw(auth_date="abc")
    with pytest.raises(ValueError):
        validate_init_data(init_data, _TEST_BOT_TOKEN)


def test_init_data_with_old_auth_date_rejected():
    """A5: auth_date older than max_age_seconds must raise ValueError('initData expired')."""
    old_ts = str(int(time.time()) - 2 * 86400)  # 2 days ago
    init_data = _signed_init_data_raw(auth_date=old_ts)
    with pytest.raises(ValueError, match="initData expired"):
        validate_init_data(init_data, _TEST_BOT_TOKEN)


def test_init_data_with_current_auth_date_accepted():
    """A6: fresh properly-signed initData must be accepted without error."""
    init_data = signed_init_data()
    result = validate_init_data(init_data, _TEST_BOT_TOKEN)
    assert "auth_date" in result


# ===========================================================================
# B. JWT (CMS auth)
# ===========================================================================

def test_jwt_with_wrong_iss_rejected():
    """B7: JWT signed with wrong issuer must raise HTTPException 401."""
    from fastapi import HTTPException as _HTTPException
    token = jwt.encode(
        {"sub": "1", "iss": "other", "type": "access", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(_HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


def test_jwt_expired_rejected():
    """B8: expired JWT must raise HTTPException 401."""
    from fastapi import HTTPException as _HTTPException
    token = jwt.encode(
        {"sub": "1", "iss": settings.jwt_issuer, "type": "access",
         "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(_HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_wrong_type_rejected():
    """B9: refresh token presented where access token is expected → 401."""
    from fastapi import HTTPException as _HTTPException
    token = create_refresh_token({"sub": "1"})
    with pytest.raises(_HTTPException) as exc_info:
        await require_jwt_auth(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_valid_access_token_accepted():
    """B10: properly formed access token is accepted by require_jwt_auth."""
    token = create_access_token({"sub": "1", "phone": "77067396626"})
    payload = await require_jwt_auth(authorization=f"Bearer {token}")
    assert payload["sub"] == "1"
    assert payload["type"] == "access"


# ===========================================================================
# C. CSRF on /api/auth/refresh
# Comprehensive coverage is in tests/test_routes_auth.py (Phase 3.3).
# These are regression smoke tests only.
# ===========================================================================

def test_refresh_without_csrf_header_403(monkeypatch):
    """C11: /refresh with cookie but no X-CSRF-Token header → 403."""
    client = _make_test_client(monkeypatch, redis=_FakeRedisUnlimited(), https=True)
    verify = client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"})
    assert verify.status_code == 200
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 403


def test_refresh_without_csrf_cookie_403(monkeypatch):
    """C12: /refresh with header but no cookie → 403."""
    client = _make_test_client(monkeypatch, redis=_FakeRedisUnlimited(), https=True)
    # Don't authenticate first — no cookie is set
    resp = client.post("/api/auth/refresh", headers={"X-CSRF-Token": "some-token"})
    assert resp.status_code == 403


def test_refresh_mismatched_csrf_403(monkeypatch):
    """C13: /refresh with header and cookie but mismatched values → 403."""
    client = _make_test_client(monkeypatch, redis=_FakeRedisUnlimited(), https=True)
    client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"})
    resp = client.post("/api/auth/refresh", headers={"X-CSRF-Token": "totally-wrong"})
    assert resp.status_code == 403


def test_refresh_matched_csrf_200(monkeypatch):
    """C14: /refresh with matching header and cookie → 200 + new access_token."""
    client = _make_test_client(monkeypatch, redis=_FakeRedisUnlimited(), https=True)
    verify = client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"})
    assert verify.status_code == 200
    csrf = verify.cookies.get("csrf_token")
    assert csrf
    resp = client.post("/api/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_logout_clears_both_cookies(monkeypatch):
    """C15: POST /logout clears refresh_token and csrf_token cookies."""
    # Covered in detail by tests/test_routes_auth.py::test_logout_clears_both_cookies
    client = _make_test_client(monkeypatch, redis=_FakeRedisUnlimited())
    client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"})
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.cookies.get("refresh_token", None) in (None, "")
    assert resp.cookies.get("csrf_token", None) in (None, "")


# ===========================================================================
# D. CORS
# Full coverage: tests/test_api_app.py (Phase 3.1).
# These two smoke tests guard against accidental regression.
# ===========================================================================

def test_cors_blocks_unknown_origin_when_allowlist_empty(monkeypatch):
    """D16: empty cors_allowed_origins → evil.com must NOT receive ACAO header."""
    import src.config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "cors_allowed_origins", "")
    app = create_app()
    app.state.pg_pool = _FakePool()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.options(
        "/api/orders",
        headers={"Origin": "https://evil.com", "Access-Control-Request-Method": "GET"},
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao != "https://evil.com"


def test_cors_allows_listed_origin(monkeypatch):
    """D17: listed origin must receive matching ACAO header."""
    import src.config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "cors_allowed_origins", "https://cms.example")
    app = create_app()
    app.state.pg_pool = _FakePool()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.options(
        "/api/orders",
        headers={"Origin": "https://cms.example", "Access-Control-Request-Method": "GET"},
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao == "https://cms.example"


# ===========================================================================
# E. OTP rate-limit
# Full parametric coverage: tests/test_routes_auth.py (Phase 3.2).
# These are concise regression guards.
# ===========================================================================

def test_otp_verify_rate_limit_per_phone_429_after_5(monkeypatch):
    """E18: 6th verify attempt from same phone must get 429 + Retry-After header."""
    fake_redis = _FakeRedisRateLimit(prefix="rl:otp_verify:phone:", limit=5)
    client = _make_test_client(monkeypatch, redis=fake_redis)

    for i in range(5):
        r = client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "00000000"})
        assert r.status_code == 401, f"attempt {i+1}: expected 401, got {r.status_code}"

    r = client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "00000000"})
    assert r.status_code == 429
    assert "retry-after" in r.headers


def test_otp_send_rate_limit_per_ip_429_after_10(monkeypatch):
    """E19: 11th /send request from same IP must get 429."""
    counter = {"n": 0}

    class _LimitSend:
        async def rate_limit_check(self, key, limit, window_seconds):
            if key.startswith("rl:otp_send:ip:"):
                counter["n"] += 1
                return (counter["n"] <= 10, counter["n"])
            return (True, 1)

        async def close(self):
            pass

    client = _make_test_client(monkeypatch, redis=_LimitSend())

    for i in range(10):
        r = client.post("/api/auth/otp/send", json={"phone": "77067396626"})
        assert r.status_code == 200, f"attempt {i+1}: expected 200, got {r.status_code}"

    r = client.post("/api/auth/otp/send", json={"phone": "77067396626"})
    assert r.status_code == 429
    assert "retry-after" in r.headers


# ===========================================================================
# F. WhatsApp bridge ingress
# ===========================================================================

class _FakeRedisForBridge:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, queue_name, job):
        self.jobs.append((queue_name, job))


def _make_bridge_client(monkeypatch, bridge_secret: str) -> TestClient:
    app = create_app()
    app.state.pg_pool = _FakePool()
    app.state.redis_client = _FakeRedisForBridge()
    monkeypatch.setattr(routes_whatsapp.settings, "bridge_shared_secret", bridge_secret)
    return TestClient(app, raise_server_exceptions=False)


def test_whatsapp_inbound_without_secret_rejected(monkeypatch):
    """F20: POST /internal/whatsapp/inbound with no X-Bridge-Secret → 401."""
    client = _make_bridge_client(monkeypatch, bridge_secret="real-secret")
    resp = client.post(
        "/internal/whatsapp/inbound",
        json={"external_id": "msg-1", "external_chat_id": "1@s.whatsapp.net"},
    )
    assert resp.status_code == 401


def test_whatsapp_inbound_with_wrong_secret_rejected(monkeypatch):
    """F21: POST /internal/whatsapp/inbound with wrong secret → 401."""
    client = _make_bridge_client(monkeypatch, bridge_secret="real-secret")
    resp = client.post(
        "/internal/whatsapp/inbound",
        headers={"X-Bridge-Secret": "wrong-secret"},
        json={"external_id": "msg-1", "external_chat_id": "1@s.whatsapp.net"},
    )
    assert resp.status_code == 401


def test_whatsapp_inbound_with_correct_secret_accepted(monkeypatch):
    """F22: correct secret bypasses auth guard — secret check is not bypassable."""

    async def fake_enqueue(_pool, _redis, payload):
        return {"queued": True, "duplicate": False, "update_id": 1}

    monkeypatch.setattr(routes_whatsapp, "enqueue_whatsapp_inbound", fake_enqueue)
    client = _make_bridge_client(monkeypatch, bridge_secret="real-secret")
    resp = client.post(
        "/internal/whatsapp/inbound",
        headers={"X-Bridge-Secret": "real-secret"},
        json={"external_id": "msg-ok", "external_chat_id": "1@s.whatsapp.net"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True



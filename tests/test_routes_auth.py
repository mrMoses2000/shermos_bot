import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from src.api.app import create_app
from src.api import routes_auth
from src.db import postgres


class FakePool:
    async def fetchrow(self, query, *args):
        return None

    async def fetchval(self, query, *args):
        return 1

    async def execute(self, query, *args):
        return "OK"


class FakeRedisUnlimited:
    """Redis stub that never rate-limits."""

    async def rate_limit_check(self, key: str, limit: int, window_seconds: int):
        return (True, 1)

    async def close(self):
        pass


class FakeRedisPhoneLimited:
    """Redis stub that hits the per-phone limit after N calls for rl:otp_verify:phone:* keys."""

    def __init__(self, phone_limit: int = 5, ip_limit: int = 20):
        self._phone_counts: dict[str, int] = {}
        self._ip_counts: dict[str, int] = {}
        self.phone_limit = phone_limit
        self.ip_limit = ip_limit

    async def rate_limit_check(self, key: str, limit: int, window_seconds: int):
        if key.startswith("rl:otp_verify:phone:"):
            self._phone_counts[key] = self._phone_counts.get(key, 0) + 1
            count = self._phone_counts[key]
            return (count <= self.phone_limit, count)
        elif key.startswith("rl:otp_verify:ip:"):
            self._ip_counts[key] = self._ip_counts.get(key, 0) + 1
            count = self._ip_counts[key]
            return (count <= self.ip_limit, count)
        elif key.startswith("rl:otp_send:ip:"):
            self._ip_counts[key] = self._ip_counts.get(key, 0) + 1
            count = self._ip_counts[key]
            return (count <= limit, count)
        return (True, 1)

    async def close(self):
        pass


def _make_client(monkeypatch, redis_state=None, otp_code="12345678"):
    """Build a TestClient with mocked DB and optional Redis state."""
    app = create_app()
    app.state.pg_pool = FakePool()
    if redis_state is not None:
        app.state.redis_client = redis_state

    async def get_otp_rate_limit(*args):
        return None

    async def update_otp_rate_limit(*args):
        return None

    async def store_otp(*args):
        return None

    async def get_manager(pool, phone):
        return {"phone_e164": phone, "is_active": True, "name": "Master"}

    async def get_otp(pool, phone):
        return {
            "phone_e164": phone,
            "code_hash": routes_auth.hash_otp(otp_code),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            "attempts": 0,
        }

    async def increment_otp_attempts(*args):
        return 1

    async def delete_otp(*args):
        return None

    monkeypatch.setattr(postgres, "get_otp_rate_limit", get_otp_rate_limit)
    monkeypatch.setattr(postgres, "update_otp_rate_limit", update_otp_rate_limit)
    monkeypatch.setattr(postgres, "store_otp", store_otp)
    monkeypatch.setattr(postgres, "get_manager", get_manager)
    monkeypatch.setattr(postgres, "get_otp", get_otp)
    monkeypatch.setattr(postgres, "increment_otp_attempts", increment_otp_attempts)
    monkeypatch.setattr(postgres, "delete_otp", delete_otp)

    async def send_message(*args, **kwargs):
        return "wamid"

    monkeypatch.setattr(routes_auth.manager_whatsapp_sender, "send_message", send_message)
    monkeypatch.setattr(routes_auth.manager_whatsapp_sender, "start", lambda: None)

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(monkeypatch):
    return _make_client(monkeypatch, redis_state=FakeRedisUnlimited(), otp_code="12345678")


# ── Original tests (updated to 8-digit OTP code) ────────────────────────────

def test_send_otp_success(client):
    response = client.post("/api/auth/otp/send", json={"phone": "77067396626"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_verify_otp_success(client):
    response = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["manager"]["phone"] == "77067396626"


def test_verify_otp_invalid_code(client, monkeypatch):
    response = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396626", "code": "wrongwrong"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid code"


# ── Step 3.2: Rate-limit tests ───────────────────────────────────────────────

def test_verify_otp_phone_rate_limit(monkeypatch):
    """After 5 wrong attempts the 6th should hit the phone rate limit (429)."""
    fake_redis = FakeRedisPhoneLimited(phone_limit=5, ip_limit=100)
    client = _make_client(monkeypatch, redis_state=fake_redis, otp_code="12345678")

    # First 5: rate-limit allows them through; OTP is wrong → 401
    for i in range(5):
        r = client.post(
            "/api/auth/otp/verify", json={"phone": "77067396626", "code": "00000000"}
        )
        assert r.status_code == 401, f"attempt {i+1} expected 401, got {r.status_code}"

    # 6th: phone counter = 6 > limit=5 → 429
    r = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396626", "code": "00000000"}
    )
    assert r.status_code == 429
    assert r.headers.get("retry-after") == "60"


def test_verify_otp_ip_rate_limit(monkeypatch):
    """After 20 attempts from same IP across multiple phones the 21st hits IP limit."""
    fake_redis = FakeRedisPhoneLimited(phone_limit=1000, ip_limit=20)
    client = _make_client(monkeypatch, redis_state=fake_redis, otp_code="12345678")

    # 20 attempts across different phone numbers
    for i in range(20):
        r = client.post(
            "/api/auth/otp/verify",
            json={"phone": f"7706739662{i % 10}", "code": "00000000"},
        )
        assert r.status_code == 401, f"attempt {i+1}: expected 401, got {r.status_code}"

    # 21st — IP counter > 20 → 429
    r = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396629", "code": "00000000"}
    )
    assert r.status_code == 429
    assert r.headers.get("retry-after") == "60"


def test_send_otp_ip_rate_limit(monkeypatch):
    """After 10 /send requests from same IP the 11th gets 429."""
    fake_redis = FakeRedisPhoneLimited(phone_limit=1000, ip_limit=1000)
    # Override send limit to 10
    real_rate_limit_check = fake_redis.rate_limit_check

    send_counter = {"count": 0}

    async def controlled_rate_limit(key, limit, window_seconds):
        if key.startswith("rl:otp_send:ip:"):
            send_counter["count"] += 1
            return (send_counter["count"] <= 10, send_counter["count"])
        return (True, 1)

    fake_redis.rate_limit_check = controlled_rate_limit

    client = _make_client(monkeypatch, redis_state=fake_redis)

    # First 10 — allowed → 200 (manager lookup returns manager)
    for i in range(10):
        r = client.post("/api/auth/otp/send", json={"phone": "77067396626"})
        assert r.status_code == 200, f"attempt {i+1}: expected 200, got {r.status_code}"

    # 11th — blocked → 429
    r = client.post("/api/auth/otp/send", json={"phone": "77067396626"})
    assert r.status_code == 429
    assert r.headers.get("retry-after") == "60"


# ── Step 3.3: CSRF tests ─────────────────────────────────────────────────────

def test_verify_otp_sets_csrf_cookie(client):
    """Successful verify should set both refresh_token (httponly) and csrf_token (not httponly) cookies."""
    response = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"}
    )
    assert response.status_code == 200
    cookies = response.cookies
    # Both cookies must be present
    assert "refresh_token" in cookies, "refresh_token cookie missing"
    assert "csrf_token" in cookies, "csrf_token cookie missing"


def test_refresh_without_csrf_header_is_403(client):
    """Calling /refresh without X-CSRF-Token header should return 403."""
    # First get a valid refresh token + csrf cookie via verify
    verify_resp = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"}
    )
    assert verify_resp.status_code == 200

    # Now call /refresh without CSRF header (cookies are sent automatically by TestClient)
    refresh_resp = client.post("/api/auth/refresh")
    assert refresh_resp.status_code == 403


def test_refresh_with_wrong_csrf_token_is_403(client):
    """Calling /refresh with mismatched X-CSRF-Token should return 403."""
    verify_resp = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"}
    )
    assert verify_resp.status_code == 200

    refresh_resp = client.post(
        "/api/auth/refresh", headers={"X-CSRF-Token": "completely-wrong-token"}
    )
    assert refresh_resp.status_code == 403


def test_refresh_with_correct_csrf_token_is_200(client):
    """Calling /refresh with matching X-CSRF-Token returns 200 + new access_token + rotated csrf cookie."""
    verify_resp = client.post(
        "/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"}
    )
    assert verify_resp.status_code == 200

    csrf_token = verify_resp.cookies.get("csrf_token")
    assert csrf_token, "csrf_token cookie should be set after verify"

    refresh_resp = client.post(
        "/api/auth/refresh", headers={"X-CSRF-Token": csrf_token}
    )
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()
    # csrf_token should be rotated (new value in Set-Cookie)
    assert "csrf_token" in refresh_resp.cookies


def test_logout_clears_both_cookies(client):
    """Logout should clear both refresh_token and csrf_token cookies."""
    # First authenticate
    client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "12345678"})

    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["ok"] is True
    # The cookie values should be empty strings (deleted)
    assert logout_resp.cookies.get("refresh_token", None) in (None, "")
    assert logout_resp.cookies.get("csrf_token", None) in (None, "")

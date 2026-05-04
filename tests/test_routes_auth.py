import pytest
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

@pytest.fixture
def client(monkeypatch):
    app = create_app()
    app.state.pg_pool = FakePool()
    
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
            "code_hash": routes_auth.hash_otp("123456"),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            "attempts": 0
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
    
    # Mock whatsapp sender
    async def send_message(*args, **kwargs):
        return "wamid"
    monkeypatch.setattr(routes_auth.manager_whatsapp_sender, "send_message", send_message)
    monkeypatch.setattr(routes_auth.manager_whatsapp_sender, "start", lambda: None)

    return TestClient(app)

def test_send_otp_success(client):
    response = client.post("/api/auth/otp/send", json={"phone": "77067396626"})
    assert response.status_code == 200
    assert response.json()["ok"] is True

def test_verify_otp_success(client):
    response = client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "123456"})
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["manager"]["phone"] == "77067396626"

def test_verify_otp_invalid_code(client, monkeypatch):
    # Overriding the verify_otp helper is tricky, so we just use the default logic but pass wrong code
    response = client.post("/api/auth/otp/verify", json={"phone": "77067396626", "code": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid code"

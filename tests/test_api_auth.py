import hashlib
import hmac
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from src.api.auth import require_auth, validate_init_data, create_access_token


def signed_init_data(bot_token: str, payload: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": digest})


def test_validate_init_data_success():
    init_data = signed_init_data(
        "manager-token",
        {"auth_date": str(int(time.time())), "query_id": "abc", "user": '{"id":1}'},
    )

    parsed = validate_init_data(init_data, "manager-token")

    assert parsed["query_id"] == "abc"
    assert parsed["user_json"]["id"] == 1


def test_validate_init_data_rejects_bad_hash():
    with pytest.raises(ValueError):
        validate_init_data("auth_date=1&hash=bad", "manager-token")


@pytest.mark.asyncio
async def test_require_auth_accepts_cms_admin_token(monkeypatch):
    monkeypatch.setattr("src.api.auth.settings.cms_admin_token", "secret-admin-token")

    parsed = await require_auth("", "secret-admin-token", "")

    assert parsed == {"auth_method": "cms_admin", "sub": "admin"}


@pytest.mark.asyncio
async def test_require_auth_rejects_bad_cms_admin_token(monkeypatch):
    monkeypatch.setattr("src.api.auth.settings.cms_admin_token", "secret-admin-token")

    with pytest.raises(HTTPException) as exc_info:
        await require_auth("", "wrong", "")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid CMS admin token"


@pytest.mark.asyncio
async def test_require_auth_accepts_jwt(monkeypatch):
    monkeypatch.setattr("src.api.auth.settings.jwt_secret", "test-secret")
    monkeypatch.setattr("src.api.auth.settings.jwt_issuer", "shermos-api")
    
    token = create_access_token({"sub": "77067396626"})
    parsed = await require_auth("", "", f"Bearer {token}")
    
    assert parsed["sub"] == "77067396626"
    assert parsed["type"] == "access"

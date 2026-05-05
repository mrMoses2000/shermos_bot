"""Telegram Mini App initData validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import secrets
import jwt
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, Depends

from src.config import settings

def hash_otp(code: str) -> str:
    # Use sha256 with secret salt for OTPs
    return hashlib.sha256(f"{settings.jwt_secret}:{code}".encode()).hexdigest()


def verify_otp(code: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_otp(code), hashed)


def generate_otp_code() -> str:
    # 6-digit numeric code
    return "".join(secrets.choice("0123456789") for _ in range(6))


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_ttl_days)
    to_encode.update({"exp": expire, "iss": settings.jwt_issuer, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days)
    to_encode.update({"exp": expire, "iss": settings.jwt_issuer, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=["HS256"], issuer=settings.jwt_issuer
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def parse_init_data(init_data: str) -> dict[str, str]:
    return dict(parse_qsl(init_data, keep_blank_values=True))


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict[str, Any]:
    data = parse_init_data(init_data)
    received_hash = data.pop("hash", "")
    if not received_hash:
        raise ValueError("Missing initData hash")

    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Invalid initData hash")

    try:
        auth_date = int(data.get("auth_date", "0") or "0")
    except (TypeError, ValueError):
        auth_date = 0
    if auth_date <= 0:
        raise ValueError("Missing or invalid auth_date")
    if time.time() - auth_date > max_age_seconds:
        raise ValueError("initData expired")

    if "user" in data:
        try:
            data["user_json"] = json.loads(data["user"])
        except json.JSONDecodeError:
            data["user_json"] = {}
    return data


async def require_jwt_auth(
    authorization: str = Header(default="", alias="Authorization"),
) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ")[1]
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload


async def require_auth(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    x_cms_admin_token: str = Header(default="", alias="X-CMS-Admin-Token"),
    authorization: str = Header(default="", alias="Authorization"),
) -> dict[str, Any]:
    # Try JWT first (new standard)
    if authorization:
        try:
            return await require_jwt_auth(authorization)
        except HTTPException:
            if not x_telegram_init_data and not x_cms_admin_token:
                raise

    # Fallback to Telegram
    if x_telegram_init_data:
        try:
            data = validate_init_data(x_telegram_init_data, settings.manager_bot_token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        data["auth_method"] = "telegram"
        return data

    # Fallback to CMS Admin Token (for setup)
    if x_cms_admin_token:
        if settings.cms_admin_token and hmac.compare_digest(x_cms_admin_token, settings.cms_admin_token):
            return {"auth_method": "cms_admin", "sub": "admin"}
        raise HTTPException(status_code=401, detail="Invalid CMS admin token")

    raise HTTPException(status_code=401, detail="Authentication required")

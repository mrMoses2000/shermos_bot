"""Telegram Mini App initData validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from src.config import settings


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

    auth_date = int(data.get("auth_date", "0") or "0")
    if auth_date and time.time() - auth_date > max_age_seconds:
        raise ValueError("initData expired")

    if "user" in data:
        try:
            data["user_json"] = json.loads(data["user"])
        except json.JSONDecodeError:
            data["user_json"] = {}
    return data


async def require_telegram_auth(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict[str, Any]:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Missing Telegram initData")
    try:
        return validate_init_data(x_telegram_init_data, settings.manager_bot_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

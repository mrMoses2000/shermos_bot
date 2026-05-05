"""Authentication routes for managers (WhatsApp OTP + JWT)."""

from __future__ import annotations

import re
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel

from src.api.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_otp_code,
    hash_otp,
    verify_otp,
)
from src.api.deps import get_pool
from src.config import settings
from src.db import postgres
from src.bot.whatsapp_sender import manager_whatsapp_sender
from src.utils.logger import setup_logger

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = setup_logger(__name__)


class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone)


def _get_client_ip(request: Request) -> str:
    """Return the client IP, falling back to 'unknown' when behind a proxy without forwarded headers."""
    host = request.client.host if request.client else None
    return host or "unknown"


@router.post("/otp/send")
async def send_otp(body: OtpRequest, request: Request, pool=Depends(get_pool)):
    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    # Generic response for privacy
    success_resp = {"ok": True, "message": "If the phone is registered, an OTP has been sent."}

    # Redis IP-based rate limit on send: 10/60s
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is not None:
        ip = _get_client_ip(request)
        allowed, _ = await redis_client.rate_limit_check(
            f"rl:otp_send:ip:{ip}", limit=10, window_seconds=60
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": "60"},
            )

    manager = await postgres.get_manager(pool, phone)
    if not manager or not manager.get("is_active"):
        logger.info("otp_request_ignored_unknown_manager", extra={"phone": phone})
        return success_resp

    # Rate limiting
    rl = await postgres.get_otp_rate_limit(pool, phone)
    now = datetime.now(timezone.utc)
    if rl:
        last_sent = rl["last_sent_at"]
        if now - last_sent < timedelta(minutes=1):
            raise HTTPException(status_code=429, detail="Too many requests. Wait 1 minute.")
        
        count_1h = rl["send_count_1h"]
        if now - last_sent > timedelta(hours=1):
            count_1h = 0
        
        if count_1h >= settings.otp_rate_limit_1h:
            raise HTTPException(status_code=429, detail="Hourly limit exceeded.")
        
        await postgres.update_otp_rate_limit(pool, phone, count_1h + 1)
    else:
        await postgres.update_otp_rate_limit(pool, phone, 1)

    code = generate_otp_code()
    expires_at = now + timedelta(minutes=settings.otp_expiry_minutes)
    await postgres.store_otp(pool, phone, hash_otp(code), expires_at)

    try:
        await manager_whatsapp_sender.start()
        await manager_whatsapp_sender.send_message(
            "",
            f"{phone}@s.whatsapp.net",
            f"Ваш код для входа в Shermos CMS: {code}\nДействует {settings.otp_expiry_minutes} минут.",
        )
        logger.info("otp_sent", extra={"phone": phone})
    except Exception as exc:
        logger.error("otp_send_failed", extra={"phone": phone, "error": str(exc)})
        # Don't fail the request, just log it. In dev it might fail if bridge is down.

    return success_resp


@router.post("/otp/verify")
async def verify_otp_route(body: OtpVerify, request: Request, response: Response, pool=Depends(get_pool)):
    phone = normalize_phone(body.phone)

    # Redis rate limits: 5/60s per phone, 20/60s per IP
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is not None:
        ip = _get_client_ip(request)
        phone_allowed, _ = await redis_client.rate_limit_check(
            f"rl:otp_verify:phone:{phone}", limit=5, window_seconds=60
        )
        ip_allowed, _ = await redis_client.rate_limit_check(
            f"rl:otp_verify:ip:{ip}", limit=20, window_seconds=60
        )
        if not phone_allowed or not ip_allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts",
                headers={"Retry-After": "60"},
            )

    otp = await postgres.get_otp(pool, phone)
    if not otp:
        raise HTTPException(status_code=401, detail="OTP not found or expired")

    if datetime.now(timezone.utc) > otp["expires_at"].replace(tzinfo=timezone.utc):
        await postgres.delete_otp(pool, phone)
        raise HTTPException(status_code=401, detail="OTP expired")

    if otp["attempts"] >= settings.otp_max_attempts:
        await postgres.delete_otp(pool, phone)
        raise HTTPException(status_code=401, detail="Too many attempts")

    if not verify_otp(body.code, otp["code_hash"]):
        await postgres.increment_otp_attempts(pool, phone)
        raise HTTPException(status_code=401, detail="Invalid code")

    await postgres.delete_otp(pool, phone)
    manager = await postgres.get_manager(pool, phone)
    if not manager or not manager.get("is_active"):
        raise HTTPException(status_code=403, detail="Manager disabled")

    user_data = {"sub": phone, "name": manager.get("name")}
    access_token = create_access_token(user_data)
    refresh_token = create_refresh_token(user_data)
    csrf_token = secrets.token_urlsafe(32)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.jwt_refresh_ttl_days * 24 * 3600,
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="none",
        max_age=settings.jwt_refresh_ttl_days * 24 * 3600,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "manager": {
            "phone": phone,
            "name": manager.get("name"),
        }
    }


@router.post("/refresh")
async def refresh_token_route(request: Request, response: Response):
    # CSRF double-submit check: cookie value must match X-CSRF-Token header
    cookie_csrf = request.cookies.get("csrf_token")
    header_csrf = request.headers.get("X-CSRF-Token")
    if not cookie_csrf or not header_csrf:
        raise HTTPException(status_code=403, detail="Missing CSRF token")
    if not hmac.compare_digest(cookie_csrf, header_csrf):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")

    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_data = {"sub": payload["sub"], "name": payload.get("name")}
    access_token = create_access_token(user_data)

    # Rotate refresh token
    new_refresh_token = create_refresh_token(user_data)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.jwt_refresh_ttl_days * 24 * 3600,
    )

    # Rotate csrf_token
    new_csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key="csrf_token",
        value=new_csrf_token,
        httponly=False,
        secure=True,
        samesite="none",
        max_age=settings.jwt_refresh_ttl_days * 24 * 3600,
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token")
    response.delete_cookie("csrf_token")
    return {"ok": True}

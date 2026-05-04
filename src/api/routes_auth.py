"""Authentication routes for managers (WhatsApp OTP + JWT)."""

from __future__ import annotations

import re
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


@router.post("/otp/send")
async def send_otp(body: OtpRequest, pool=Depends(get_pool)):
    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    # Generic response for privacy
    success_resp = {"ok": True, "message": "If the phone is registered, an OTP has been sent."}

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
async def verify_otp_route(body: OtpVerify, response: Response, pool=Depends(get_pool)):
    phone = normalize_phone(body.phone)
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

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
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
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_data = {"sub": payload["sub"], "name": payload.get("name")}
    access_token = create_access_token(user_data)
    
    # Optional: Rotate refresh token
    new_refresh_token = create_refresh_token(user_data)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.jwt_refresh_ttl_days * 24 * 3600,
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token")
    return {"ok": True}

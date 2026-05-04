"""HTTP client for the local WhatsApp bridge service."""

from __future__ import annotations

import re
import uuid
from html import unescape
from pathlib import Path
from typing import Any

import aiohttp

from src.config import settings


def _plain_text(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip() or " "


def _button_title(text: str) -> str:
    return _plain_text(text).replace("\n", " ")[:20] or "Выбрать"


def _reply_markup_to_payload(text: str, reply_markup: dict | None) -> dict[str, Any]:
    base_text = _plain_text(text)
    if not isinstance(reply_markup, dict):
        return {"text": base_text}

    rows = reply_markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return {"text": base_text}

    buttons: list[dict[str, str]] = []
    url: str | None = None
    for row in rows:
        if not isinstance(row, list):
            continue
        for button in row:
            if not isinstance(button, dict):
                continue
            callback_data = button.get("callback_data")
            title = button.get("text")
            if callback_data and title:
                buttons.append({"id": str(callback_data), "title": _button_title(str(title))})
                continue
            web_app = button.get("web_app") if isinstance(button.get("web_app"), dict) else {}
            url = url or web_app.get("url") or button.get("url")

    if url:
        base_text = f"{base_text}\n\n{url}".strip()

    if not buttons:
        return {"text": base_text}

    # Native interactive buttons (1–3) or list (4+)
    if len(buttons) <= 3:
        interactive: dict[str, Any] = {
            "type": "buttons",
            "buttons": buttons,
        }
    else:
        interactive = {
            "type": "list",
            "list": {
                "button_text": "Выбрать",
                "sections": [
                    {
                        "title": "Действия",
                        "rows": buttons,
                    }
                ],
            },
        }

    return {"text": base_text, "interactive": interactive}


class WhatsAppSender:
    channel = "whatsapp"

    def __init__(self, *, role: str = "client") -> None:
        self.role = role
        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()

    def _require_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            raise RuntimeError("WhatsAppSender session is not started")
        return self.session

    def _url(self, path: str) -> str:
        base_url = settings.whatsapp_bridge_url
        if self.role == "manager" and settings.manager_whatsapp_bridge_url:
            base_url = settings.manager_whatsapp_bridge_url
        return f"{base_url.rstrip('/')}{path}"

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-Bridge-Secret": settings.bridge_shared_secret}
        async with self._require_session().post(self._url(path), json=payload, headers=headers) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"WhatsApp bridge {path} failed: {data}")
            return data

    async def send_message(
        self,
        token: str,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
        idempotency_key: str | None = None,
    ) -> str | None:
        payload = {
            "to": str(chat_id),
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
        }
        payload.update(_reply_markup_to_payload(text, reply_markup))
        data = await self._post_json("/send", payload)
        message_id = data.get("message_id")
        return str(message_id) if message_id is not None else None

    async def send_photo(
        self,
        token: str,
        chat_id: int | str,
        photo_path: str,
        caption: str = "",
    ) -> dict[str, Any]:
        payload = {
            "to": str(chat_id),
            "idempotency_key": str(uuid.uuid4()),
            "text": _plain_text(caption),
            "media": {
                "type": "image",
                "path": str(Path(photo_path)),
                "caption": _plain_text(caption),
            },
        }
        return await self._post_json("/send", payload)

    async def send_media_group(
        self,
        token: str,
        chat_id: int | str,
        photo_paths: list[str],
        caption: str = "",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "skipped"}
        for index, photo_path in enumerate(photo_paths):
            result = await self.send_photo(
                token,
                chat_id,
                photo_path,
                caption=caption if index == 0 else "",
            )
        return result

    async def send_chat_action(self, token: str, chat_id: int | str, action: str = "typing") -> dict[str, Any]:
        return {"ok": True}


whatsapp_sender = WhatsAppSender()
manager_whatsapp_sender = WhatsAppSender(role="manager")

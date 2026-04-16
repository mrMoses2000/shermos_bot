"""Raw aiohttp Telegram Bot API client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiohttp


class TelegramSender:
    def __init__(self) -> None:
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
            raise RuntimeError("TelegramSender session is not started")
        return self.session

    def _url(self, token: str, method: str) -> str:
        return f"https://api.telegram.org/bot{token}/{method}"

    async def _post_json(self, token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._require_session().post(self._url(token, method), json=payload) as response:
            data = await response.json(content_type=None)
            if response.status >= 400 or not data.get("ok", False):
                raise RuntimeError(f"Telegram {method} failed: {data}")
            return data

    async def _post_form(self, token: str, method: str, form: aiohttp.FormData) -> dict[str, Any]:
        async with self._require_session().post(self._url(token, method), data=form) as response:
            data = await response.json(content_type=None)
            if response.status >= 400 or not data.get("ok", False):
                raise RuntimeError(f"Telegram {method} failed: {data}")
            return data

    async def send_message(
        self,
        token: str,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> int | None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        data = await self._post_json(token, "sendMessage", payload)
        return data.get("result", {}).get("message_id")

    async def send_photo(
        self,
        token: str,
        chat_id: int,
        photo_path: str,
        caption: str = "",
    ) -> dict[str, Any]:
        path = Path(photo_path)
        with path.open("rb") as photo_file:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption)
                form.add_field("parse_mode", "HTML")
            form.add_field(
                "photo",
                photo_file,
                filename=path.name,
                content_type="image/png",
            )
            return await self._post_form(token, "sendPhoto", form)

    async def send_media_group(
        self,
        token: str,
        chat_id: int,
        photo_paths: list[str],
        caption: str = "",
    ) -> dict[str, Any]:
        files = []
        try:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            media = []
            for index, photo_path in enumerate(photo_paths):
                path = Path(photo_path)
                handle = path.open("rb")
                files.append(handle)
                media_item = {"type": "photo", "media": f"attach://photo{index}"}
                if index == 0 and caption:
                    media_item["caption"] = caption
                    media_item["parse_mode"] = "HTML"
                media.append(media_item)
                form.add_field(
                    f"photo{index}",
                    handle,
                    filename=path.name,
                    content_type="image/png",
                )
            form.add_field("media", json.dumps(media, ensure_ascii=False))
            return await self._post_form(token, "sendMediaGroup", form)
        finally:
            for handle in files:
                handle.close()

    async def send_chat_action(self, token: str, chat_id: int, action: str = "typing") -> dict[str, Any]:
        return await self._post_json(token, "sendChatAction", {"chat_id": chat_id, "action": action})

    async def edit_message(
        self,
        token: str,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        return await self._post_json(
            token,
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode},
        )

    async def set_webhook(
        self,
        token: str,
        url: str,
        secret_token: str,
        allowed_updates: list[str],
        certificate_path: str | None = None,
    ) -> dict[str, Any]:
        if certificate_path:
            path = Path(certificate_path)
            with path.open("rb") as cert_file:
                form = aiohttp.FormData()
                form.add_field("url", url)
                form.add_field("secret_token", secret_token)
                form.add_field("allowed_updates", json.dumps(allowed_updates))
                form.add_field(
                    "certificate",
                    cert_file,
                    filename=path.name,
                    content_type="application/x-pem-file",
                )
                return await self._post_form(token, "setWebhook", form)
        return await self._post_json(
            token,
            "setWebhook",
            {"url": url, "secret_token": secret_token, "allowed_updates": allowed_updates},
        )

    async def delete_webhook(self, token: str) -> dict[str, Any]:
        return await self._post_json(token, "deleteWebhook", {"drop_pending_updates": False})

    async def set_chat_menu_button(self, token: str, chat_id: int, menu_button: dict) -> dict[str, Any]:
        return await self._post_json(
            token,
            "setChatMenuButton",
            {"chat_id": chat_id, "menu_button": menu_button},
        )

    async def answer_callback_query(
        self,
        token: str,
        callback_query_id: str,
        text: str = "",
    ) -> dict[str, Any]:
        return await self._post_json(
            token,
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text},
        )

    async def get_file(self, token: str, file_id: str) -> dict[str, Any]:
        data = await self._post_json(token, "getFile", {"file_id": file_id})
        result = data.get("result") or {}
        if not result.get("file_path"):
            raise RuntimeError(f"Telegram getFile returned no file_path for {file_id}")
        return result

    async def download_file(self, token: str, file_path: str) -> bytes:
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        session = self._require_session()
        async with session.get(url) as response:
            if response.status >= 400:
                raise RuntimeError(
                    f"Telegram file download failed ({response.status}) for {file_path}"
                )
            return await response.read()


telegram_sender = TelegramSender()


async def send_message(*args, **kwargs):
    return await telegram_sender.send_message(*args, **kwargs)


async def send_photo(*args, **kwargs):
    return await telegram_sender.send_photo(*args, **kwargs)


async def send_media_group(*args, **kwargs):
    return await telegram_sender.send_media_group(*args, **kwargs)


async def send_chat_action(*args, **kwargs):
    return await telegram_sender.send_chat_action(*args, **kwargs)


async def edit_message(*args, **kwargs):
    return await telegram_sender.edit_message(*args, **kwargs)


async def set_webhook(*args, **kwargs):
    return await telegram_sender.set_webhook(*args, **kwargs)


async def delete_webhook(*args, **kwargs):
    return await telegram_sender.delete_webhook(*args, **kwargs)


async def set_chat_menu_button(*args, **kwargs):
    return await telegram_sender.set_chat_menu_button(*args, **kwargs)


async def answer_callback_query(*args, **kwargs):
    return await telegram_sender.answer_callback_query(*args, **kwargs)


async def get_file(*args, **kwargs):
    return await telegram_sender.get_file(*args, **kwargs)


async def download_file(*args, **kwargs):
    return await telegram_sender.download_file(*args, **kwargs)

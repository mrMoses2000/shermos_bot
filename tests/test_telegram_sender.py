import json

import pytest

from src.bot.telegram_sender import TelegramSender


@pytest.mark.asyncio
async def test_sender_requires_started_session():
    sender = TelegramSender()

    with pytest.raises(RuntimeError):
        sender._require_session()


def test_sender_url_contract():
    assert TelegramSender()._url("token", "sendMessage").endswith("/bottoken/sendMessage")


@pytest.mark.asyncio
async def test_send_message_builds_payload(monkeypatch):
    sender = TelegramSender()
    calls = []

    async def fake_post_json(token, method, payload):
        calls.append((token, method, payload))
        return {"ok": True}

    monkeypatch.setattr(sender, "_post_json", fake_post_json)

    result = await sender.send_message("tok", 10, "hello", reply_markup={"k": 1})

    assert result["ok"] is True
    assert calls == [
        (
            "tok",
            "sendMessage",
            {
                "chat_id": 10,
                "text": "hello",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {"k": 1},
            },
        )
    ]


@pytest.mark.asyncio
async def test_simple_telegram_methods(monkeypatch):
    sender = TelegramSender()
    calls = []

    async def fake_post_json(token, method, payload):
        calls.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(sender, "_post_json", fake_post_json)

    await sender.send_chat_action("tok", 1, "typing")
    await sender.edit_message("tok", 1, 2, "edited")
    await sender.delete_webhook("tok")
    await sender.set_chat_menu_button("tok", 1, {"type": "commands"})
    await sender.answer_callback_query("tok", "cb", "ok")

    assert [method for method, _payload in calls] == [
        "sendChatAction",
        "editMessageText",
        "deleteWebhook",
        "setChatMenuButton",
        "answerCallbackQuery",
    ]
    assert calls[1][1]["message_id"] == 2


@pytest.mark.asyncio
async def test_send_photo_and_media_group_use_form(monkeypatch, tmp_path):
    sender = TelegramSender()
    calls = []
    photo = tmp_path / "a.png"
    photo.write_bytes(b"png")
    photo2 = tmp_path / "b.png"
    photo2.write_bytes(b"png")

    async def fake_post_form(token, method, form):
        calls.append((token, method, form))
        return {"ok": True}

    monkeypatch.setattr(sender, "_post_form", fake_post_form)

    await sender.send_photo("tok", 1, str(photo), caption="cap")
    await sender.send_media_group("tok", 1, [str(photo), str(photo2)], caption="group")

    assert calls[0][1] == "sendPhoto"
    assert calls[1][1] == "sendMediaGroup"


@pytest.mark.asyncio
async def test_set_webhook_json_and_certificate(monkeypatch, tmp_path):
    sender = TelegramSender()
    calls = []
    cert = tmp_path / "webhook.pem"
    cert.write_text("CERT")

    async def fake_post_json(token, method, payload):
        calls.append(("json", token, method, payload))
        return {"ok": True}

    async def fake_post_form(token, method, form):
        calls.append(("form", token, method, form))
        return {"ok": True}

    monkeypatch.setattr(sender, "_post_json", fake_post_json)
    monkeypatch.setattr(sender, "_post_form", fake_post_form)

    await sender.set_webhook("tok", "https://example.com", "secret", ["message"])
    await sender.set_webhook("tok", "https://example.com", "secret", ["message"], str(cert))

    assert calls[0][0:3] == ("json", "tok", "setWebhook")
    assert calls[0][3]["allowed_updates"] == ["message"]
    assert calls[1][0:3] == ("form", "tok", "setWebhook")


@pytest.mark.asyncio
async def test_post_json_raises_on_telegram_error(monkeypatch):
    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self, content_type=None):
            return {"ok": False, "description": "bad"}

    class FakeSession:
        closed = False

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    sender = TelegramSender()
    sender.session = FakeSession()

    with pytest.raises(RuntimeError):
        await sender._post_json("tok", "sendMessage", {})

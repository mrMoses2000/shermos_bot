import pytest

from src.bot.whatsapp_sender import WhatsAppSender, _plain_text


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, content_type=None):
        return {"message_id": "wamid-1", "status": "sent"}


class FakeSession:
    closed = False

    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return FakeResponse()


def test_plain_text_strips_html():
    assert _plain_text("<b>Привет</b><br>мир") == "Привет\nмир"


@pytest.mark.asyncio
async def test_whatsapp_sender_posts_to_bridge(monkeypatch):
    sender = WhatsAppSender()
    fake_session = FakeSession()
    sender.session = fake_session
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.whatsapp_bridge_url", "http://bridge.local")
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.bridge_shared_secret", "secret")

    message_id = await sender.send_message(
        "",
        77064264520,
        "<b>Hi</b>",
        idempotency_key="00000000-0000-4000-8000-000000000001",
    )

    assert message_id == "wamid-1"
    url, payload, headers = fake_session.calls[0]
    assert url == "http://bridge.local/send"
    assert headers == {"X-Bridge-Secret": "secret"}
    assert payload == {
        "to": "77064264520",
        "idempotency_key": "00000000-0000-4000-8000-000000000001",
        "text": "Hi",
    }


@pytest.mark.asyncio
async def test_manager_whatsapp_sender_posts_to_manager_bridge(monkeypatch):
    sender = WhatsAppSender(role="manager")
    fake_session = FakeSession()
    sender.session = fake_session
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.whatsapp_bridge_url", "http://client.local")
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.manager_whatsapp_bridge_url", "http://manager.local")
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.bridge_shared_secret", "secret")

    await sender.send_message(
        "",
        77067396626,
        "Manager",
        idempotency_key="00000000-0000-4000-8000-000000000011",
    )

    url, payload, _headers = fake_session.calls[0]
    assert url == "http://manager.local/send"
    assert payload["to"] == "77067396626"


@pytest.mark.asyncio
async def test_whatsapp_sender_maps_small_inline_keyboard_to_buttons(monkeypatch):
    sender = WhatsAppSender()
    fake_session = FakeSession()
    sender.session = fake_session
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.whatsapp_bridge_url", "http://bridge.local")
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.bridge_shared_secret", "secret")

    await sender.send_message(
        "",
        77064264520,
        "Выберите действие",
        reply_markup={
            "inline_keyboard": [[
                {"text": "Да", "callback_data": "gallery_yes"},
                {"text": "Нет", "callback_data": "gallery_no"},
            ]]
        },
        idempotency_key="00000000-0000-4000-8000-000000000002",
    )

    _, payload, _ = fake_session.calls[0]
    assert payload["interactive"] == {
        "type": "buttons",
        "buttons": [
            {"id": "gallery_yes", "title": "Да"},
            {"id": "gallery_no", "title": "Нет"},
        ],
    }
    assert payload["text"] == "Выберите действие"


@pytest.mark.asyncio
async def test_whatsapp_sender_maps_large_inline_keyboard_to_list(monkeypatch):
    sender = WhatsAppSender()
    fake_session = FakeSession()
    sender.session = fake_session
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.whatsapp_bridge_url", "http://bridge.local")
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.bridge_shared_secret", "secret")

    await sender.send_message(
        "",
        77064264520,
        "Оцените рендер",
        reply_markup={
            "inline_keyboard": [[
                {"text": "⭐1", "callback_data": "rate:1"},
                {"text": "⭐2", "callback_data": "rate:2"},
                {"text": "⭐3", "callback_data": "rate:3"},
                {"text": "⭐4", "callback_data": "rate:4"},
                {"text": "⭐5", "callback_data": "rate:5"},
            ]]
        },
        idempotency_key="00000000-0000-4000-8000-000000000003",
    )

    _, payload, _ = fake_session.calls[0]
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["list"]["button_text"] == "Выбрать"
    assert payload["interactive"]["list"]["sections"][0]["rows"] == [
        {"id": "rate:1", "title": "⭐1"},
        {"id": "rate:2", "title": "⭐2"},
        {"id": "rate:3", "title": "⭐3"},
        {"id": "rate:4", "title": "⭐4"},
        {"id": "rate:5", "title": "⭐5"},
    ]


@pytest.mark.asyncio
async def test_whatsapp_sender_appends_web_app_url_when_present(monkeypatch):
    sender = WhatsAppSender()
    fake_session = FakeSession()
    sender.session = fake_session
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.whatsapp_bridge_url", "http://bridge.local")
    monkeypatch.setattr("src.bot.whatsapp_sender.settings.bridge_shared_secret", "secret")

    await sender.send_message(
        "",
        77064264520,
        "Открыть CMS",
        reply_markup={
            "inline_keyboard": [[
                {"text": "Открыть CMS", "web_app": {"url": "https://example.com/app"}},
            ]]
        },
        idempotency_key="00000000-0000-4000-8000-000000000004",
    )

    _, payload, _ = fake_session.calls[0]
    assert payload == {
        "to": "77064264520",
        "idempotency_key": "00000000-0000-4000-8000-000000000004",
        "text": "Открыть CMS\n\nhttps://example.com/app",
    }

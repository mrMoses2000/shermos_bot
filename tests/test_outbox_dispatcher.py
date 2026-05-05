import asyncio

import pytest

from src.bot.errors import PermanentSendError
from src.queue import outbox_dispatcher
from tests.helpers import FakeSender, FakeWhatsAppSender


@pytest.mark.asyncio
async def test_dispatch_once_marks_success_and_failure(monkeypatch):
    """Non-whatsapp events (e.g. legacy Telegram) are marked dead; whatsapp events are dispatched."""
    events = [
        {"id": 1, "chat_id": 10, "channel": "telegram", "bot_type": "client", "reply_text": "ok", "reply_markup": None},
        {"id": 2, "chat_id": 11, "channel": "telegram", "bot_type": "manager", "reply_text": "bad", "reply_markup": None},
    ]
    calls = []

    async def fake_get_pending(_pool, limit=20):
        return events

    async def fake_mark_dead(_pool, event_id, error):
        calls.append(("dead", event_id, error))

    async def fake_mark_failed(_pool, event_id, error):
        calls.append(("failed", event_id, error))

    monkeypatch.setattr(outbox_dispatcher.postgres, "get_pending_outbound", fake_get_pending)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_dead", fake_mark_dead)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_failed", fake_mark_failed)

    sent = await outbox_dispatcher.dispatch_once(object())

    # Both telegram events should be marked dead (decommissioned)
    assert sent == 0
    assert len([c for c in calls if c[0] == "dead"]) == 2


@pytest.mark.asyncio
async def test_run_outbox_dispatcher_propagates_cancel(monkeypatch):
    async def fake_dispatch_once(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(outbox_dispatcher, "dispatch_once", fake_dispatch_once)

    with pytest.raises(asyncio.CancelledError):
        await outbox_dispatcher.run_outbox_dispatcher(object(), interval=0)


@pytest.mark.asyncio
async def test_dispatch_once_sends_whatsapp_event(monkeypatch):
    events = [
        {
            "id": 7,
            "chat_id": 77064264520,
            "channel": "whatsapp",
            "external_chat_id": "77064264520",
            "bot_type": "client",
            "reply_text": "ok",
            "reply_markup": None,
            "idempotency_key": "00000000-0000-4000-8000-000000000007",
        },
    ]
    calls = []

    async def fake_get_pending(_pool, limit=20):
        return events

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None, external_message_id=None):
        calls.append(("sent", event_id, telegram_message_id, external_message_id))

    async def fake_mark_failed(_pool, event_id, error):
        calls.append(("failed", event_id, error))

    class _WASender:
        async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None, idempotency_key=None):
            calls.append(("send", token, chat_id, text, idempotency_key))
            return "wa-msg-7"

    monkeypatch.setattr(outbox_dispatcher.postgres, "get_pending_outbound", fake_get_pending)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_failed", fake_mark_failed)
    monkeypatch.setattr(outbox_dispatcher, "whatsapp_sender", _WASender())

    sent = await outbox_dispatcher.dispatch_once(object())

    assert sent == 1
    assert ("send", "", "77064264520", "ok", "00000000-0000-4000-8000-000000000007") in calls
    assert ("sent", 7, None, "wa-msg-7") in calls


@pytest.mark.asyncio
async def test_dispatch_once_sends_manager_whatsapp_event_to_manager_bridge(monkeypatch):
    events = [
        {
            "id": 8,
            "chat_id": 77067396626,
            "channel": "whatsapp",
            "external_chat_id": "77067396626",
            "bot_type": "manager",
            "reply_text": "manager ok",
            "reply_markup": None,
            "idempotency_key": "00000000-0000-4000-8000-000000000008",
        },
    ]
    calls = []

    async def fake_get_pending(_pool, limit=20):
        return events

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None, external_message_id=None):
        calls.append(("sent", event_id, telegram_message_id, external_message_id))

    async def fake_mark_failed(_pool, event_id, error):
        calls.append(("failed", event_id, error))

    class ClientWhatsAppSender:
        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("client WhatsApp sender should not be used")

    class ManagerWhatsAppSender:
        async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None, idempotency_key=None):
            calls.append(("manager_send", token, chat_id, text, idempotency_key))
            return "manager-wa-msg-8"

    monkeypatch.setattr(outbox_dispatcher.postgres, "get_pending_outbound", fake_get_pending)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_failed", fake_mark_failed)
    monkeypatch.setattr(outbox_dispatcher, "whatsapp_sender", ClientWhatsAppSender())
    monkeypatch.setattr(outbox_dispatcher, "manager_whatsapp_sender", ManagerWhatsAppSender())

    sent = await outbox_dispatcher.dispatch_once(object())

    assert sent == 1
    assert ("manager_send", "", "77067396626", "manager ok", "00000000-0000-4000-8000-000000000008") in calls
    assert ("sent", 8, None, "manager-wa-msg-8") in calls


@pytest.mark.asyncio
async def test_dispatch_once_calls_mark_dead_on_permanent_error(monkeypatch):
    """PermanentSendError routes to mark_outbound_dead, not mark_outbound_failed."""
    events = [
        {
            "id": 42,
            "chat_id": 99,
            "channel": "whatsapp",
            "external_chat_id": "99@s.whatsapp.net",
            "bot_type": "client",
            "reply_text": "hi",
            "reply_markup": None,
            "idempotency_key": None,
        },
    ]
    calls = []

    async def fake_get_pending(_pool, limit=20):
        return events

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None, external_message_id=None):
        calls.append(("sent", event_id))

    async def fake_mark_failed(_pool, event_id, error):
        calls.append(("failed", event_id, error))

    async def fake_mark_dead(_pool, event_id, error):
        calls.append(("dead", event_id, error))

    class BlockedSender:
        async def send_message(self, token, chat_id, text, reply_markup=None, idempotency_key=None, **kwargs):
            raise PermanentSendError(403, "Forbidden: bot was blocked by the user")

    monkeypatch.setattr(outbox_dispatcher.postgres, "get_pending_outbound", fake_get_pending)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_failed", fake_mark_failed)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_dead", fake_mark_dead)
    monkeypatch.setattr(outbox_dispatcher, "whatsapp_sender", BlockedSender())

    sent = await outbox_dispatcher.dispatch_once(object())

    assert sent == 0
    dead_calls = [c for c in calls if c[0] == "dead"]
    failed_calls = [c for c in calls if c[0] == "failed"]
    assert len(dead_calls) == 1
    assert dead_calls[0][1] == 42
    assert "blocked" in dead_calls[0][2]
    assert len(failed_calls) == 0

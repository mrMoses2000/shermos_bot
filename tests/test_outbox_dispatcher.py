import asyncio

import pytest

from src.queue import outbox_dispatcher
from tests.helpers import FakeSender


@pytest.mark.asyncio
async def test_dispatch_once_marks_success_and_failure(monkeypatch):
    events = [
        {"id": 1, "chat_id": 10, "bot_type": "client", "reply_text": "ok", "reply_markup": None},
        {"id": 2, "chat_id": 11, "bot_type": "manager", "reply_text": "bad", "reply_markup": None},
    ]
    calls = []

    async def fake_get_pending(_pool, limit=20):
        return events

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None):
        calls.append(("sent", event_id, telegram_message_id))

    async def fake_mark_failed(_pool, event_id, error):
        calls.append(("failed", event_id, error))

    class Sender(FakeSender):
        async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None):
            if text == "bad":
                raise RuntimeError("telegram down")
            return await super().send_message(token, chat_id, text, parse_mode, reply_markup)

    monkeypatch.setattr(outbox_dispatcher.postgres, "get_pending_outbound", fake_get_pending)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_failed", fake_mark_failed)

    sent = await outbox_dispatcher.dispatch_once(object(), Sender())

    assert sent == 1
    assert ("sent", 1, 1) in calls
    assert calls[-1][0:2] == ("failed", 2)


@pytest.mark.asyncio
async def test_run_outbox_dispatcher_propagates_cancel(monkeypatch):
    async def fake_dispatch_once(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(outbox_dispatcher, "dispatch_once", fake_dispatch_once)

    with pytest.raises(asyncio.CancelledError):
        await outbox_dispatcher.run_outbox_dispatcher(object(), FakeSender(), interval=0)

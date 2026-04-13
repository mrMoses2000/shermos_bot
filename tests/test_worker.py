import pytest

from src.models import Job
from src.queue import worker


class FakeSender:
    def __init__(self):
        self.messages = []

    async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None):
        self.messages.append((token, chat_id, text, reply_markup))
        return {"ok": True}

    async def send_chat_action(self, *_args, **_kwargs):
        return {"ok": True}


@pytest.mark.asyncio
async def test_handle_clear_command(monkeypatch):
    calls = []

    async def clear_chat_messages(_pool, chat_id):
        calls.append(("clear", chat_id))

    async def upsert_conversation_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))

    async def insert_outbound_event(*_args, **_kwargs):
        return 42

    async def mark_outbound_sent(_pool, event_id):
        calls.append(("sent", event_id))

    monkeypatch.setattr(worker.postgres, "clear_chat_messages", clear_chat_messages)
    monkeypatch.setattr(worker.postgres, "upsert_conversation_state", upsert_conversation_state)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", insert_outbound_event)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", mark_outbound_sent)
    sender = FakeSender()
    job = Job(update_id=1, chat_id=100, user_id=100, text="/clear", msg_type="command")

    handled = await worker._handle_client_command(job, object(), sender)

    assert handled is True
    assert ("clear", 100) in calls
    assert sender.messages[0][2] == "История диалога очищена."

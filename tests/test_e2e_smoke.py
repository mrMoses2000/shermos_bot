import pytest

from src.bot import webhook
from src.models import Job
from src.queue import worker
from tests.helpers import FakeRedis, FakeSender


class FakeRequest:
    def __init__(self, payload, redis):
        self.headers = {"X-Telegram-Bot-Api-Secret-Token": "client-secret"}
        self.app = {"pg_pool": object(), "redis": redis}
        self._payload = payload

    async def json(self):
        return self._payload


class MemoryPostgres:
    def __init__(self):
        self.statuses = []
        self.messages = []
        self.outbound = []
        self.clients = {}

    async def mark_update_received(self, _pool, update_id):
        return True

    async def insert_inbound_event(self, _pool, update_id, chat_id, user_id, text, raw_update):
        return 1

    async def mark_update_status(self, _pool, update_id, status, error=None):
        self.statuses.append((update_id, status, error))

    async def insert_outbound_event(self, _pool, chat_id, reply_text, reply_markup=None, inbound_event_id=None, bot_type="client"):
        self.outbound.append((chat_id, reply_text, bot_type))
        return len(self.outbound)

    async def mark_outbound_sent(self, _pool, event_id, telegram_message_id=None):
        self.statuses.append(("outbound", event_id, "sent", telegram_message_id))

    async def get_client_by_chat_id(self, _pool, chat_id):
        return self.clients.get(chat_id)

    async def create_client(self, _pool, chat_id, first_name="", username=""):
        self.clients[chat_id] = {"chat_id": chat_id, "first_name": first_name, "username": username}
        return self.clients[chat_id]

    async def get_conversation_state(self, _pool, chat_id):
        return {"mode": "idle", "step": None, "collected_params": {}}

    async def get_chat_messages(self, _pool, chat_id, limit=20):
        return []

    async def insert_chat_message(self, _pool, chat_id, role, text):
        self.messages.append((chat_id, role, text))
        return len(self.messages)


@pytest.mark.asyncio
async def test_e2e_smoke_webhook_to_worker_with_mocked_llm(monkeypatch):
    memory_pg = MemoryPostgres()
    redis = FakeRedis()
    sender = FakeSender()
    payload = {
        "update_id": 501,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 200, "first_name": "Ivan", "username": "ivan"},
            "text": "Нужна перегородка",
        },
    }

    for name in (
        "mark_update_received",
        "insert_inbound_event",
    ):
        monkeypatch.setattr(webhook.postgres, name, getattr(memory_pg, name))
    for name in (
        "mark_update_status",
        "insert_outbound_event",
        "mark_outbound_sent",
        "get_client_by_chat_id",
        "create_client",
        "get_conversation_state",
        "get_chat_messages",
        "insert_chat_message",
    ):
        monkeypatch.setattr(worker.postgres, name, getattr(memory_pg, name))

    async def fake_call_llm(_prompt):
        return '{"reply_text": "Уточните высоту.", "actions": {"state_patch": {"mode": "collecting", "step": "ask_height", "collected_params": {"shape": "Прямая"}}}}'

    async def fake_apply_actions(*_args, **_kwargs):
        return {"render_paths": None, "price": None, "calendar_event": None, "order": None}

    monkeypatch.setattr(worker, "call_llm", fake_call_llm)
    monkeypatch.setattr(worker, "apply_actions", fake_apply_actions)

    response = await webhook._process_webhook(FakeRequest(payload, redis), "client", "client-secret")
    assert response.status == 200
    queue_name, job = redis.jobs.pop()
    assert queue_name == "queue:incoming"
    assert isinstance(job, Job)

    await worker.process_client_job(job, object(), redis, sender)

    assert sender.messages[0]["text"] == "Уточните высоту."
    assert (100, "assistant", "Уточните высоту.") in memory_pg.messages
    assert (501, "completed", None) in memory_pg.statuses

import pytest

from src.bot import webhook


class FakeRequest:
    def __init__(self, payload, secret="client-secret"):
        self.headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
        self.app = {"pg_pool": object(), "redis": FakeRedis()}
        self._payload = payload

    async def json(self):
        return self._payload


class FakeRedis:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, queue_name, job):
        self.jobs.append((queue_name, job))


@pytest.mark.asyncio
async def test_process_webhook_enqueues_job(monkeypatch):
    calls = {}

    async def mark_update_received(_pool, update_id):
        calls["update_id"] = update_id
        return True

    async def insert_inbound_event(_pool, update_id, chat_id, user_id, text, raw_update):
        calls["inbound"] = (update_id, chat_id, user_id, text, raw_update)
        return 1

    monkeypatch.setattr(webhook.postgres, "mark_update_received", mark_update_received)
    monkeypatch.setattr(webhook.postgres, "insert_inbound_event", insert_inbound_event)
    request = FakeRequest(
        {
            "update_id": 10,
            "message": {
                "chat": {"id": 100},
                "from": {"id": 200},
                "text": "/start",
            },
        }
    )

    response = await webhook._process_webhook(request, "client", "client-secret")

    assert response.status == 200
    assert calls["update_id"] == 10
    assert request.app["redis"].jobs[0][0] == "queue:incoming"
    assert request.app["redis"].jobs[0][1].msg_type == "command"


@pytest.mark.asyncio
async def test_process_webhook_ignores_bad_secret(monkeypatch):
    async def fail_if_called(*_args):
        raise AssertionError("should not be called")

    monkeypatch.setattr(webhook.postgres, "mark_update_received", fail_if_called)
    request = FakeRequest({"update_id": 10}, secret="wrong")

    response = await webhook._process_webhook(request, "client", "client-secret")

    assert response.status == 200


def test_extract_update_callback_and_photo():
    callback = {
        "callback_query": {
            "from": {"id": 20},
            "data": "confirm_render",
            "message": {"chat": {"id": 10}},
        }
    }
    assert webhook._extract_update(callback) == (
        10,
        20,
        "confirm_render",
        "callback_query",
        "confirm_render",
    )

    photo = {"message": {"chat": {"id": 1}, "from": {"id": 2}, "photo": [{}], "caption": "вид"}}
    assert webhook._extract_update(photo) == (1, 2, "вид", "photo", "")

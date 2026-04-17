import pytest

from src.models import Job
from src.queue import worker
from tests.helpers import FakeRedis, FakeSender


@pytest.mark.asyncio
async def test_locked_client_job_requeues(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    redis = FakeRedis(locked=True)
    job = Job(update_id=1, chat_id=10, user_id=10, text="hi", attempt=2)

    await worker.process_client_job(job, object(), redis, FakeSender())

    assert redis.jobs[0][0] == "queue:incoming"
    assert redis.jobs[0][1].attempt == 3
    assert slept == [4]


@pytest.mark.asyncio
async def test_send_render_result_uses_media_group():
    sender = FakeSender()
    job = Job(update_id=1, chat_id=10, user_id=10, text="hi")
    result = {
        "render_paths": {"0deg": "/tmp/a.png", "90deg": "/tmp/b.png"},
        "order": {"request_id": "order1"},
        "price": {"total_price": 100, "currency": "USD"},
    }

    await worker._send_render_result(job, object(), sender, result)

    assert sender.media_groups
    assert "order1" in sender.media_groups[0][3]
    assert sender.messages[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("gallery_show")


@pytest.mark.asyncio
async def test_manager_job_orders_and_status(monkeypatch):
    calls = []

    async def fake_mark_status(_pool, update_id, status, error=None):
        calls.append(("status", update_id, status))

    async def fake_insert_outbound(*_args, **kwargs):
        calls.append(("outbound", kwargs.get("bot_type")))
        return 1

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None):
        calls.append(("sent", event_id, telegram_message_id))

    async def fake_list_orders(_pool, limit=10):
        return [{"request_id": "r1", "status": "new"}]

    async def fake_update_order_status(_pool, order_id, status):
        calls.append(("order_status", order_id, status))
        return {"request_id": order_id, "status": status}

    async def fake_get_status(*_a, **_kw):
        return None

    monkeypatch.setattr(worker.postgres, "get_update_status", fake_get_status)
    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert_outbound)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(worker.postgres, "list_orders", fake_list_orders)
    monkeypatch.setattr(worker.postgres, "update_order_status", fake_update_order_status)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=1, chat_id=99, user_id=99, text="/orders", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )
    await worker.process_manager_job(
        Job(update_id=2, chat_id=99, user_id=99, text="", callback_data="order_status:r1:completed", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert "r1" in sender.messages[0]["text"]
    assert ("order_status", "r1", "completed") in calls


@pytest.mark.asyncio
async def test_manager_job_fallback_command(monkeypatch):
    async def fake_mark_status(*_args, **_kwargs):
        return None

    async def fake_insert_outbound(*_args, **_kwargs):
        return 1

    async def fake_mark_sent(*_args, **_kwargs):
        return None

    async def fake_get_status(*_a, **_kw):
        return None

    monkeypatch.setattr(worker.postgres, "get_update_status", fake_get_status)
    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert_outbound)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", fake_mark_sent)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=1, chat_id=99, user_id=99, text="unknown", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert "Команды" in sender.messages[0]["text"]


@pytest.mark.asyncio
async def test_already_completed_job_is_skipped(monkeypatch):
    """If processed_updates already has status=completed, job must not be re-processed."""
    called = []

    async def fake_get_status(_pool, update_id):
        return "completed"

    async def fake_mark_status(*_a, **_kw):
        called.append("mark_status")

    monkeypatch.setattr(worker.postgres, "get_update_status", fake_get_status)
    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)

    sender = FakeSender()
    job = Job(update_id=42, chat_id=10, user_id=10, text="hi")
    await worker.process_client_job(job, object(), FakeRedis(), sender)

    assert not called, "mark_update_status must not be called for already-completed job"
    assert not sender.messages, "No messages must be sent for already-completed job"

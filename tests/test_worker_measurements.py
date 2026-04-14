from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.models import Job
from src.queue import worker
from tests.helpers import FakeRedis, FakeSender


TZ = ZoneInfo("Asia/Bishkek")


@pytest.fixture
def manager_db(monkeypatch):
    calls = []

    async def fake_mark_status(_pool, update_id, status, error=None):
        calls.append(("update_status", update_id, status, error))

    async def fake_insert_outbound(*_args, **kwargs):
        calls.append(("outbound", kwargs.get("chat_id"), kwargs.get("bot_type"), kwargs.get("reply_text")))
        return len(calls)

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None):
        calls.append(("sent", event_id, telegram_message_id))

    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert_outbound)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", fake_mark_sent)
    return calls


@pytest.mark.asyncio
async def test_meas_confirm_notifies_client(monkeypatch, manager_db):
    scheduled_time = datetime.now(TZ) + timedelta(days=1)

    async def fake_update_status(_pool, measurement_id, new_status, manager_chat_id=None, reason=""):
        assert measurement_id == 42
        assert new_status == "confirmed"
        assert manager_chat_id == 99
        return {
            "id": 42,
            "client_chat_id": 123,
            "scheduled_time": scheduled_time,
            "address": "Бишкек",
        }

    import src.engine.measurement_service as measurement_service

    monkeypatch.setattr(measurement_service, "update_measurement_status", fake_update_status)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=1, chat_id=99, user_id=99, callback_data="meas_confirm:42", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert any(message["chat_id"] == 123 and "подтверждён" in message["text"] for message in sender.messages)
    assert ("update_status", 1, "completed", None) in manager_db


@pytest.mark.asyncio
async def test_meas_reject_notifies_client(monkeypatch, manager_db):
    scheduled_time = datetime.now(TZ) + timedelta(days=1)

    async def fake_update_status(_pool, measurement_id, new_status, manager_chat_id=None, reason=""):
        assert new_status == "rejected"
        return {
            "id": measurement_id,
            "client_chat_id": 124,
            "scheduled_time": scheduled_time,
            "address": "Бишкек",
        }

    import src.engine.measurement_service as measurement_service

    monkeypatch.setattr(measurement_service, "update_measurement_status", fake_update_status)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=2, chat_id=99, user_id=99, callback_data="meas_reject:43", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert any("не может быть проведён" in message["text"] for message in sender.messages)


@pytest.mark.asyncio
async def test_meas_call_returns_phone(monkeypatch, manager_db):
    async def fake_fetchrow(_pool, measurement_id):
        assert measurement_id == 55
        return {"id": 55, "client_phone": "+996555111222"}

    monkeypatch.setattr(worker, "pool_fetchrow_safe", fake_fetchrow)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=3, chat_id=99, user_id=99, callback_data="meas_call:55", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert "+996555111222" in sender.messages[0]["text"]


@pytest.mark.asyncio
async def test_measurements_command_lists_upcoming(monkeypatch, manager_db):
    scheduled_time = datetime.now(TZ) + timedelta(days=1)

    async def fake_list_measurements(_pool, upcoming_only=True, limit=10):
        assert upcoming_only is True
        assert limit == 10
        return [{"id": 9, "scheduled_time": scheduled_time, "client_name": "Айбек", "status": "scheduled"}]

    monkeypatch.setattr(worker.postgres, "list_measurements", fake_list_measurements)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=4, chat_id=99, user_id=99, text="/measurements", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert "Ближайшие замеры" in sender.messages[0]["text"]
    assert "#9" in sender.messages[0]["text"]
    assert "Айбек" in sender.messages[0]["text"]

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

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))
        return {"chat_id": chat_id, "mode": mode, "step": step, "collected_params": collected_params}

    async def fake_get_state(_pool, chat_id):
        return None

    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert_outbound)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(worker.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(worker.postgres, "get_conversation_state", fake_get_state)
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
    assert any(call[0] == "state" and call[2] == "scheduling" for call in manager_db)


@pytest.mark.asyncio
async def test_meas_reject_after_auto_confirm_cancels_and_notifies_client(monkeypatch, manager_db):
    scheduled_time = datetime.now(TZ) + timedelta(days=1)
    calls = []

    async def fake_update_status(_pool, measurement_id, new_status, manager_chat_id=None, reason=""):
        calls.append(new_status)
        if new_status == "rejected":
            raise ValueError("Нельзя перевести")
        assert new_status == "cancelled"
        return {
            "id": measurement_id,
            "client_chat_id": 124,
            "scheduled_time": scheduled_time,
            "address": "Бишкек",
        }

    async def fake_fetchrow(_pool, measurement_id):
        return {"id": measurement_id, "status": "confirmed"}

    import src.engine.measurement_service as measurement_service

    monkeypatch.setattr(measurement_service, "update_measurement_status", fake_update_status)
    monkeypatch.setattr(worker, "pool_fetchrow_safe", fake_fetchrow)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=22, chat_id=99, user_id=99, callback_data="meas_reject:43", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert calls == ["rejected", "cancelled"]
    assert any("выберите другое время" in message["text"] for message in sender.messages)


@pytest.mark.asyncio
async def test_manager_slot_proposal_saves_open_slot(monkeypatch, manager_db):
    slot_start = datetime.now(TZ) + timedelta(days=1)

    async def fake_get_state(_pool, chat_id):
        return {"mode": "scheduling", "step": "measurement_alt:43", "collected_params": {"measurement_id": 43}}

    async def fake_upsert_slot(_pool, date, time, timezone, manager_chat_id=None):
        assert manager_chat_id == 99
        return {"id": 1, "slot_start": slot_start, "status": "open"}

    import src.engine.measurement_service as measurement_service

    monkeypatch.setattr(worker.postgres, "get_conversation_state", fake_get_state)
    monkeypatch.setattr(measurement_service, "upsert_measurement_slot", fake_upsert_slot)
    sender = FakeSender()

    await worker.process_manager_job(
        Job(update_id=23, chat_id=99, user_id=99, text="завтра 11:00", bot_type="manager"),
        object(),
        FakeRedis(),
        sender,
    )

    assert any("Открытый слот сохранён" in message["text"] for message in sender.messages)


@pytest.mark.asyncio
async def test_notify_auto_confirmed_measurements(monkeypatch, manager_db):
    monkeypatch.setattr(worker.settings, "manager_chat_ids", "99")
    scheduled_time = datetime.now(TZ) + timedelta(days=1)
    sender = FakeSender()

    await worker._notify_auto_confirmed_measurements(
        object(),
        sender,
        [{"id": 5, "client_chat_id": 123, "scheduled_time": scheduled_time, "address": "Бишкек"}],
    )

    assert any("автоматически подтверждён" in message["text"] for message in sender.messages)
    assert any(message["chat_id"] == 99 for message in sender.messages)


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

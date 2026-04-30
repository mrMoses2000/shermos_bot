import pytest

from src.models import Job
from src.queue import worker
from tests.helpers import FakeRedis, FakeSender


@pytest.mark.asyncio
async def test_locked_client_job_requeues(monkeypatch):
    redis = FakeRedis(locked=True)
    job = Job(update_id=1, chat_id=10, user_id=10, text="hi", attempt=2)

    await worker.process_client_job(job, object(), redis, FakeSender())

    assert not redis.jobs
    assert redis.scheduled[0][0] == worker.CLIENT_DELAYED_QUEUE
    assert redis.scheduled[0][1].attempt == 3
    assert redis.scheduled[0][2] == 4


@pytest.mark.asyncio
async def test_locked_client_job_never_silently_drops_after_five_attempts():
    redis = FakeRedis(locked=True)
    job = Job(update_id=1, chat_id=10, user_id=10, text="hi", attempt=5)

    await worker.process_client_job(job, object(), redis, FakeSender())

    assert redis.scheduled[0][1].attempt == 6
    assert redis.scheduled[0][2] == 15


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
async def test_manager_whatsapp_job_uses_manager_whatsapp_sender(monkeypatch):
    calls = []

    async def fake_mark_status(_pool, update_id, status, error=None):
        calls.append(("status", update_id, status))

    async def fake_insert_outbound(_pool, **kwargs):
        calls.append(("outbound", kwargs))
        return 1

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None, external_message_id=None):
        calls.append(("sent", event_id, telegram_message_id, external_message_id))

    async def fake_get_status(*_a, **_kw):
        return None

    class ManagerWhatsAppSender:
        channel = "whatsapp"

        async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None, idempotency_key=None):
            calls.append(("send", token, chat_id, text, idempotency_key))
            return "manager-wa-msg-1"

    monkeypatch.setattr(worker.postgres, "get_update_status", fake_get_status)
    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert_outbound)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(worker, "manager_whatsapp_sender", ManagerWhatsAppSender())

    await worker.process_manager_job(
        Job(
            update_id=101,
            chat_id=77067396626,
            user_id=77067396626,
            text="/health",
            channel="whatsapp",
            bot_type="manager",
            external_chat_id="77067396626@s.whatsapp.net",
        ),
        object(),
        FakeRedis(),
    )

    outbound = next(call[1] for call in calls if call[0] == "outbound")
    assert outbound["bot_type"] == "manager"
    assert outbound["channel"] == "whatsapp"
    assert outbound["external_chat_id"] == "77067396626"
    assert any(call[0] == "send" and call[2] == 77067396626 for call in calls)
    assert ("sent", 1, None, "manager-wa-msg-1") in calls


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


@pytest.mark.asyncio
async def test_process_client_job_surfaces_validation_error(monkeypatch):
    calls = []

    async def fake_get_status(_pool, update_id):
        return None

    async def fake_mark_status(_pool, update_id, status, error=None):
        calls.append(("status", update_id, status, error))

    async def fake_get_client(_pool, chat_id):
        return {"chat_id": chat_id}

    async def fake_get_state(_pool, chat_id):
        return {"mode": "scheduling", "step": "ask_time", "collected_params": {}}

    async def fake_get_history(_pool, chat_id, limit):
        return []

    async def fake_insert_chat_message(_pool, chat_id, role, text):
        calls.append(("history", chat_id, role, text))

    async def fake_insert_outbound(*_args, **_kwargs):
        return 1

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None):
        calls.append(("sent", event_id, telegram_message_id))

    async def fake_apply_actions(*_args, **_kwargs):
        raise ValueError("Это время занято. Выберите другое время.")

    async def fake_load_slots(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(worker.postgres, "get_update_status", fake_get_status)
    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)
    monkeypatch.setattr(worker.postgres, "get_client_by_chat_id", fake_get_client)
    monkeypatch.setattr(worker.postgres, "get_conversation_state", fake_get_state)
    monkeypatch.setattr(worker.postgres, "get_chat_messages", fake_get_history)
    monkeypatch.setattr(worker.postgres, "insert_chat_message", fake_insert_chat_message)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert_outbound)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(worker, "_load_available_slots", fake_load_slots)
    monkeypatch.setattr(worker, "build_prompt", lambda *_args, **_kwargs: "PROMPT")
    async def fake_call_llm(*_args, **_kwargs):
        return '{"reply_text":"ok","actions":null}'

    monkeypatch.setattr(worker, "call_llm", fake_call_llm)

    class Parsed:
        reply_text = "ok"
        actions = {"schedule_measurement": {"date": "2026-04-23", "time": "11:00", "client_name": "Анна", "phone": "+1", "address": "Addr"}}

    monkeypatch.setattr(worker, "parse_actions", lambda _raw: Parsed())
    monkeypatch.setattr(worker, "apply_actions", fake_apply_actions)

    sender = FakeSender()
    job = Job(update_id=7, chat_id=10, user_id=10, text="запиши на 11")

    await worker.process_client_job(job, object(), FakeRedis(), sender)

    assert sender.messages[0]["text"] == "Это время занято. Выберите другое время."
    assert ("status", 7, "completed", None) in calls
    assert ("history", 10, "assistant", "Это время занято. Выберите другое время.") in calls


@pytest.mark.asyncio
async def test_process_client_job_timeout_keeps_user_message_in_history(monkeypatch):
    calls = []

    async def fake_get_status(_pool, update_id):
        return None

    async def fake_mark_status(_pool, update_id, status, error=None):
        calls.append(("status", update_id, status, error))

    async def fake_get_client(_pool, chat_id):
        return {"chat_id": chat_id}

    async def fake_get_state(_pool, chat_id):
        return {"mode": "collecting", "step": "asking_materials", "collected_params": {}}

    async def fake_get_history(_pool, chat_id, limit):
        return []

    async def fake_insert_chat_message(_pool, chat_id, role, text):
        calls.append(("history", chat_id, role, text))

    async def fake_insert_outbound(*_args, **_kwargs):
        return 1

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None):
        calls.append(("sent", event_id, telegram_message_id))

    async def fake_load_slots(*_args, **_kwargs):
        return {}

    async def fake_call_llm(*_args, **_kwargs):
        raise TimeoutError("Gemini CLI timed out")

    monkeypatch.setattr(worker.postgres, "get_update_status", fake_get_status)
    monkeypatch.setattr(worker.postgres, "mark_update_status", fake_mark_status)
    monkeypatch.setattr(worker.postgres, "get_client_by_chat_id", fake_get_client)
    monkeypatch.setattr(worker.postgres, "get_conversation_state", fake_get_state)
    monkeypatch.setattr(worker.postgres, "get_chat_messages", fake_get_history)
    monkeypatch.setattr(worker.postgres, "insert_chat_message", fake_insert_chat_message)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert_outbound)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", fake_mark_sent)
    monkeypatch.setattr(worker, "_load_available_slots", fake_load_slots)
    monkeypatch.setattr(worker, "build_prompt", lambda *_args, **_kwargs: "PROMPT")
    monkeypatch.setattr(worker, "call_llm", fake_call_llm)

    sender = FakeSender()
    job = Job(update_id=8, chat_id=10, user_id=10, text="бронзовое стекло")

    await worker.process_client_job(job, object(), FakeRedis(), sender)

    assert "Я сохранил ваше сообщение" in sender.messages[0]["text"]
    assert ("history", 10, "user", "бронзовое стекло") in calls
    assert any(call[:3] == ("history", 10, "assistant") for call in calls)
    assert ("status", 8, "failed", "Gemini CLI timed out") in calls

@pytest.mark.asyncio
async def test_auto_confirm_whatsapp_client_uses_whatsapp_sender(monkeypatch):
    calls = []
    
    async def fake_get_last_inbound_event(_pool, chat_id):
        return {"channel": "whatsapp", "external_chat_id": "phone@s.whatsapp.net"}
        
    async def fake_send_and_record(pg_pool, active_sender, token, chat_id, text, bot_type, reply_markup=None):
        calls.append((active_sender.__class__.__name__, chat_id))
        if active_sender == worker.whatsapp_sender:
            raise Exception("Simulation of failure")

    monkeypatch.setattr(worker.postgres, "get_last_inbound_event", fake_get_last_inbound_event)
    monkeypatch.setattr(worker, "_send_and_record", fake_send_and_record)
    
    import types
    fake_settings = types.SimpleNamespace(
        telegram_bot_token="token",
        manager_bot_token="manager_token",
        manager_chat_ids_list=[100],
        manager_whatsapp_numbers_list=[]
    )
    monkeypatch.setattr(worker, "settings", fake_settings)
    
    measurements = [{"id": 1, "client_chat_id": 10, "scheduled_time": worker.datetime.now(), "address": "test"}]
    
    await worker._notify_auto_confirmed_measurements(object(), FakeSender(), measurements)
    
    assert len(calls) == 2
    assert ("WhatsAppSender", "phone@s.whatsapp.net") in calls
    assert ("FakeSender", 100) in calls

@pytest.mark.asyncio
async def test_auto_confirm_client_failure_does_not_block_manager_notifications(monkeypatch):
    calls = []
    
    async def fake_get_last_inbound_event(_pool, chat_id):
        return None
        
    async def fake_send_and_record(pg_pool, active_sender, token, chat_id, text, bot_type, reply_markup=None):
        calls.append((active_sender.__class__.__name__, chat_id))
        if chat_id == 10:
            raise Exception("Telegram sending failed")

    monkeypatch.setattr(worker.postgres, "get_last_inbound_event", fake_get_last_inbound_event)
    monkeypatch.setattr(worker, "_send_and_record", fake_send_and_record)
    
    import types
    fake_settings = types.SimpleNamespace(
        telegram_bot_token="token",
        manager_bot_token="manager_token",
        manager_chat_ids_list=[100],
        manager_whatsapp_numbers_list=[]
    )
    monkeypatch.setattr(worker, "settings", fake_settings)
    
    measurements = [{"id": 1, "client_chat_id": 10, "scheduled_time": worker.datetime.now(), "address": "test"}]
    
    await worker._notify_auto_confirmed_measurements(object(), FakeSender(), measurements)
    
    assert len(calls) == 2
    assert ("FakeSender", 10) in calls
    assert ("FakeSender", 100) in calls

@pytest.mark.asyncio
async def test_manager_whatsapp_notifications_still_use_manager_allowlist_number(monkeypatch):
    calls = []
    
    async def fake_get_last_inbound_event(_pool, chat_id):
        return {"channel": "telegram"}
        
    async def fake_send_and_record(pg_pool, active_sender, token, chat_id, text, bot_type, reply_markup=None):
        if hasattr(active_sender, "role"):
            calls.append(("WhatsAppSenderManager", chat_id))
        else:
            calls.append(("FakeSender", chat_id))

    monkeypatch.setattr(worker.postgres, "get_last_inbound_event", fake_get_last_inbound_event)
    monkeypatch.setattr(worker, "_send_and_record", fake_send_and_record)
    
    import types
    fake_settings = types.SimpleNamespace(
        telegram_bot_token="token",
        manager_bot_token="manager_token",
        manager_chat_ids_list=[],
        manager_whatsapp_numbers_list=["77085766841"]
    )
    monkeypatch.setattr(worker, "settings", fake_settings)
    
    measurements = [{"id": 1, "client_chat_id": 10, "scheduled_time": worker.datetime.now(), "address": "test"}]
    
    await worker._notify_auto_confirmed_measurements(object(), FakeSender(), measurements)
    
    assert ("WhatsAppSenderManager", "77085766841") in calls

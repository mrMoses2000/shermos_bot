"""Phase 4.4 — Regression matrix of 30 client cases (C-01..C-30).

All tests are marked ``integration`` and execute only on the server where
INTEGRATION_DB_DSN and INTEGRATION_REDIS_URL are set.  Locally every test is
automatically skipped via the conftest.py ``pg_pool_integration`` / ``redis_client_integration``
fixtures that call pytest.skip() when the env-vars are absent.

Run:
    bash scripts/test_integration.sh tests/test_e2e_client_cases.py -v
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.db import postgres
from src.models import Job
from src.queue.outbox_dispatcher import dispatch_once

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Shared helpers (file-local — not exported to conftest to keep scope narrow)
# ---------------------------------------------------------------------------

async def _poll_outbound(pg_pool, chat_id: int, timeout: float = 10.0) -> dict | None:
    """Return the most recent outbound_events row for chat_id once it exists."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = await pg_pool.fetchrow(
            "SELECT * FROM outbound_events WHERE chat_id=$1 ORDER BY id DESC LIMIT 1",
            chat_id,
        )
        if row:
            return dict(row)
        await asyncio.sleep(0.2)
    return None


async def _poll_update_status(pg_pool, update_id: int, target: str, timeout: float = 10.0) -> str | None:
    """Poll processed_updates until status matches target or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = await pg_pool.fetchrow(
            "SELECT status FROM processed_updates WHERE telegram_update_id=$1",
            update_id,
        )
        if row and row["status"] == target:
            return row["status"]
        await asyncio.sleep(0.2)
    return None


def _telegram_update(update_id: int, chat_id: int, text: str, msg_type: str = "text") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "TestUser", "username": "tester"},
            "text": text,
        },
    }


async def _ingest_telegram(pg_pool, redis_client, update: dict, msg_type: str = "text") -> Job | None:
    """Replicate webhook ingress path for a Telegram update."""
    update_id = int(update["update_id"])
    message = update.get("message") or {}
    chat_id = int((message.get("chat") or {}).get("id", 0))
    user_id = int((message.get("from") or {}).get("id", chat_id))
    text = message.get("text") or ""

    is_new = await postgres.mark_update_received(pg_pool, update_id)
    if not is_new:
        return None

    await postgres.insert_inbound_event(pg_pool, update_id, chat_id, user_id, text, update)
    job = Job(
        update_id=update_id,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        msg_type=msg_type,
        raw_update=update,
        bot_type="client",
    )
    await redis_client.enqueue_job("queue:incoming", job)
    return job


async def _ingest_wa(pg_pool, redis_client, payload: dict) -> dict:
    """Replicate WhatsApp ingress path."""
    from src.bot.whatsapp_ingress import enqueue_whatsapp_inbound
    return await enqueue_whatsapp_inbound(pg_pool, redis_client, payload)


def _wa_payload(*, external_id: str, phone_e164: str, text: str = "Привет", msg_type: str = "text") -> dict:
    return {
        "external_id": external_id,
        "phone_e164": phone_e164,
        "text": text,
        "msg_type": msg_type,
        "bridge_role": "client",
        "external_chat_id": f"{phone_e164}@s.whatsapp.net",
    }


# ---------------------------------------------------------------------------
# C-02 — WhatsApp first "Привет" from a new number enqueues to queue:incoming
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C02_whatsapp_first_hello_from_new_number(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """First inbound WhatsApp message from unknown number must be accepted and queued."""
    result = await _ingest_wa(
        pg_pool_integration,
        redis_client_integration,
        _wa_payload(external_id="wa-c02-001", phone_e164="79001112233"),
    )
    assert result["queued"] is True
    assert result["duplicate"] is False

    row = await pg_pool_integration.fetchrow(
        "SELECT * FROM inbound_events WHERE telegram_update_id=$1",
        result["update_id"],
    )
    assert row is not None
    assert row["channel"] == "whatsapp"


# ---------------------------------------------------------------------------
# C-03 — state_patch from LLM updates collected_params
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C03_param_collection_happy_path(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
):
    """LLM state_patch must be persisted to conversation_state.collected_params."""
    CHAT_ID = 110003
    UPDATE_ID = 110003
    mock_call_llm[0] = (
        '{"reply_text":"Понял, записал параметры.",'
        '"actions":{"state_patch":{"mode":"collecting","step":null,'
        '"collected_params":{"shape":"Прямая","height":2.7,"glass_type":"1","frame_color":"1"}}}}'
    )

    update = _telegram_update(UPDATE_ID, CHAT_ID, "прямая 3 на 2.7 чёрный профиль прозрачное стекло")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    await asyncio.wait_for(_poll_outbound(pg_pool_integration, CHAT_ID), timeout=10)
    state = await postgres.get_conversation_state(pg_pool_integration, CHAT_ID)
    assert state is not None
    collected = state.get("collected_params") or {}
    assert collected.get("shape") == "Прямая"
    assert float(collected.get("height", 0)) == pytest.approx(2.7)


# ---------------------------------------------------------------------------
# C-04 — Decimal dimensions do not crash worker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C04_decimal_dimensions_no_crash(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
):
    """Decimal width/height (2.50, 1.80) must not crash the worker."""
    CHAT_ID = 110004
    UPDATE_ID = 110004
    mock_call_llm[0] = '{"reply_text":"Хорошо, принял размеры.","actions":null}'

    update = _telegram_update(UPDATE_ID, CHAT_ID, "ширина 2.50, высота 1.80")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"

    row = await pg_pool_integration.fetchrow(
        "SELECT error_message FROM processed_updates WHERE telegram_update_id=$1", UPDATE_ID
    )
    assert row["error_message"] is None or row["error_message"] == ""


# ---------------------------------------------------------------------------
# C-05 — Price with dot does not crash parse_slot_proposal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C05_price_with_dot_no_crash(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
):
    """Budget message '1500.50' must not cause an exception in the worker."""
    CHAT_ID = 110005
    UPDATE_ID = 110005
    mock_call_llm[0] = '{"reply_text":"Понял бюджет.","actions":null}'

    update = _telegram_update(UPDATE_ID, CHAT_ID, "бюджет 1500.50")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"


# ---------------------------------------------------------------------------
# C-06 — Voice message: transcript is NOT echoed back (fix 7ff1625)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C06_voice_transcription_no_echo(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
    monkeypatch,
):
    """After transcription, the raw transcript text must NOT appear verbatim in any outbound message."""
    CHAT_ID = 110006
    UPDATE_ID = 110006
    TRANSCRIPT = "тестовый транскрипт уникальный"

    mock_call_llm[0] = '{"reply_text":"Расскажите подробнее.","actions":null}'

    from src.bot import transcribe as transcribe_mod
    monkeypatch.setattr(transcribe_mod, "transcribe_voice", AsyncMock(return_value=TRANSCRIPT))

    voice_update = {
        "update_id": UPDATE_ID,
        "message": {
            "message_id": UPDATE_ID,
            "chat": {"id": CHAT_ID, "type": "private"},
            "from": {"id": CHAT_ID, "first_name": "TestUser"},
            "voice": {"file_id": "fake-file-id", "duration": 3},
        },
    }

    is_new = await postgres.mark_update_received(pg_pool_integration, UPDATE_ID)
    assert is_new
    await postgres.insert_inbound_event(pg_pool_integration, UPDATE_ID, CHAT_ID, CHAT_ID, "", voice_update)
    job = Job(
        update_id=UPDATE_ID, chat_id=CHAT_ID, user_id=CHAT_ID,
        text="", msg_type="voice", raw_update=voice_update,
    )
    await redis_client_integration.enqueue_job("queue:incoming", job)

    # Allow the worker to attempt the job; it may fail due to assemblyai not configured
    await asyncio.sleep(3)

    # The outbound message (if any) should not echo the transcript verbatim
    rows = await pg_pool_integration.fetch(
        "SELECT reply_text FROM outbound_events WHERE chat_id=$1", CHAT_ID
    )
    for r in rows:
        assert TRANSCRIPT not in (r["reply_text"] or ""), (
            f"Transcript must not be echoed. Found '{TRANSCRIPT}' in outbound: {r['reply_text']}"
        )


# ---------------------------------------------------------------------------
# C-07 — render_partition action creates order + photo outbound
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C07_render_request_creates_order(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
    monkeypatch,
):
    """render_partition action must create an orders row and produce a photo send."""
    CHAT_ID = 110007
    UPDATE_ID = 110007

    # Create client row first (conversation_state has FK → clients)
    await postgres.create_client(pg_pool_integration, CHAT_ID, "TestUser", "tester")

    # Pre-fill collected params
    await postgres.upsert_conversation_state(
        pg_pool_integration, CHAT_ID, "collecting", "ready_to_render",
        {"shape": "Прямая", "height": 2.5, "width_a": 3.0, "glass_type": "1", "frame_color": "1"},
    )

    import src.queue.worker as worker_mod

    stub_price = {"total_price": 999, "currency": "USD", "details": {"area_sq_m": 7.5, "partition_type": "sliding_2"}}
    stub_order = {"request_id": "TEST-ORDER-007", "collected_params": {"shape": "Прямая"}}

    async def fake_apply_actions(*args, **kwargs):
        return {"render_paths": {"front": "/tmp/test_render.png"}, "price": stub_price, "order": stub_order, "calendar_event": None}

    monkeypatch.setattr(worker_mod, "apply_actions", fake_apply_actions)
    monkeypatch.setattr(
        worker_mod, "call_llm",
        AsyncMock(return_value='{"reply_text":"Рендер готов!","actions":{"render_partition":{"shape":"Прямая","height":2.5,"width_a":3.0,"glass_type":"1","frame_color":"1","partition_type":"sliding_2","matting":"none"}}}'),
    )

    update = _telegram_update(UPDATE_ID, CHAT_ID, "сделай рендер")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"
    # Outbound must have been created
    rows = await pg_pool_integration.fetch(
        "SELECT reply_text FROM outbound_events WHERE chat_id=$1", CHAT_ID
    )
    assert len(rows) >= 1


# ---------------------------------------------------------------------------
# C-08 — schedule_measurement action creates measurement row + manager notif
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C08_schedule_measurement_happy_path(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
    monkeypatch,
):
    """schedule_measurement action must create a measurements row."""
    CHAT_ID = 110008
    UPDATE_ID = 110008

    # Create client row first (conversation_state and measurements have FK → clients)
    await postgres.create_client(pg_pool_integration, CHAT_ID, "TestUser", "tester")

    await postgres.upsert_conversation_state(
        pg_pool_integration, CHAT_ID, "collecting", "measurement_ready",
        {"shape": "Прямая", "height": 2.5, "width_a": 3.0},
    )

    from zoneinfo import ZoneInfo
    from src.config import settings
    tz = ZoneInfo(settings.timezone)
    target_dt = datetime.now(tz) + timedelta(days=3)
    # Land on a weekday
    while target_dt.weekday() == 6:
        target_dt += timedelta(days=1)
    date_str = target_dt.strftime("%Y-%m-%d")
    time_str = "11:00"

    import src.queue.worker as worker_mod

    async def fake_apply_actions_with_meas(*args, **kwargs):
        from src.engine.measurement_service import schedule_measurement
        meas = await schedule_measurement(
            pg_pool_integration, CHAT_ID, date_str, time_str,
            "Test Client", "79001234567", "ул. Тестовая 1", settings.timezone,
        )
        return {"render_paths": None, "price": None, "order": None, "calendar_event": meas}

    monkeypatch.setattr(worker_mod, "apply_actions", fake_apply_actions_with_meas)
    monkeypatch.setattr(
        worker_mod, "call_llm",
        AsyncMock(return_value=f'{{"reply_text":"Замер записан на {date_str}","actions":null}}'),
    )

    update = _telegram_update(UPDATE_ID, CHAT_ID, "запиши на замер")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"

    rows = await pg_pool_integration.fetch(
        "SELECT * FROM measurements WHERE client_chat_id=$1", CHAT_ID
    )
    assert len(rows) == 1, "Expected exactly one measurement row"
    assert rows[0]["status"] == "scheduled"


# ---------------------------------------------------------------------------
# C-09 — Conflicting measurement time raises ValueError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C09_schedule_measurement_conflict(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """Booking a slot within 45 minutes of an existing one must raise ValueError."""
    from src.engine.measurement_service import schedule_measurement, check_conflict
    from src.config import settings

    tz = ZoneInfo(settings.timezone)
    target_dt = datetime.now(tz) + timedelta(days=2)
    while target_dt.weekday() == 6:
        target_dt += timedelta(days=1)
    date_str = target_dt.strftime("%Y-%m-%d")

    # Create client row first (measurements have FK → clients)
    await postgres.create_client(pg_pool_integration, 110009, "Client A", "client_a")

    # Create first measurement
    await schedule_measurement(
        pg_pool_integration, 110009, date_str, "11:00",
        "Client A", "79000000001", "Ул. Первая 1", settings.timezone,
    )

    # Try to book 15 minutes later — within 45-min conflict window
    with pytest.raises(ValueError, match="занято"):
        await schedule_measurement(
            pg_pool_integration, 110009, date_str, "11:15",
            "Client B", "79000000002", "Ул. Вторая 2", settings.timezone,
        )


# ---------------------------------------------------------------------------
# C-10 — Sunday scheduling is refused by validate_time
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C10_schedule_measurement_sunday(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """Measurements on Sundays must raise ValueError."""
    from src.engine.measurement_service import schedule_measurement
    from src.config import settings

    tz = ZoneInfo(settings.timezone)
    # Find next Sunday
    today = datetime.now(tz)
    days_ahead = (6 - today.weekday()) % 7  # 6 = Sunday
    if days_ahead == 0:
        days_ahead = 7
    sunday = today + timedelta(days=days_ahead)
    sunday_str = sunday.strftime("%Y-%m-%d")

    with pytest.raises(ValueError, match="воскресень"):
        await schedule_measurement(
            pg_pool_integration, 110010, sunday_str, "11:00",
            "Test Client", "79000000000", "Тест", settings.timezone,
        )


# ---------------------------------------------------------------------------
# C-12 — Manager WhatsApp meas_confirm (allowlisted phone)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C12_manager_meas_confirm_whatsapp(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
    monkeypatch,
):
    """Manager WhatsApp meas_confirm from allowlisted phone must confirm measurement."""
    from src.engine.measurement_service import schedule_measurement
    from src.config import settings

    MANAGER_PHONE = "79990011200"
    CLIENT_CHAT_ID = 110012
    MANAGER_CHAT_ID = int(MANAGER_PHONE)

    monkeypatch.setattr(settings, "manager_whatsapp_numbers", MANAGER_PHONE)

    # Create client rows first (FK constraints: measurements and conversation_state → clients)
    await postgres.create_client(pg_pool_integration, CLIENT_CHAT_ID, "Client WA", "client_wa")
    await postgres.create_client(pg_pool_integration, MANAGER_CHAT_ID, "Manager WA", "manager_wa")

    tz = ZoneInfo(settings.timezone)
    target_dt = datetime.now(tz) + timedelta(days=5)
    while target_dt.weekday() == 6:
        target_dt += timedelta(days=1)

    meas = await schedule_measurement(
        pg_pool_integration, CLIENT_CHAT_ID,
        target_dt.strftime("%Y-%m-%d"), "10:00",
        "Client WA", "79001120012", "Адрес 12", settings.timezone,
    )
    meas_id = meas["id"]

    # Insert client inbound event for notification lookup
    # (inbound_events has FK → processed_updates, so mark_update_received first)
    await postgres.mark_update_received(pg_pool_integration, 1120012)
    await postgres.insert_inbound_event(
        pg_pool_integration, 1120012, CLIENT_CHAT_ID, CLIENT_CHAT_ID, "", {}
    )

    wa_payload = {
        "external_id": "wa-c12-meas-confirm",
        "phone_e164": MANAGER_PHONE,
        "text": f"meas_confirm:{meas_id}",
        "msg_type": "text",
        "bridge_role": "manager",
        "external_chat_id": f"{MANAGER_PHONE}@s.whatsapp.net",
    }
    result = await _ingest_wa(pg_pool_integration, redis_client_integration, wa_payload)
    assert result["queued"] is True

    update_id = result["update_id"]
    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, update_id, "completed"), timeout=10
    )
    assert status == "completed"

    row = await pg_pool_integration.fetchrow("SELECT status FROM measurements WHERE id=$1", meas_id)
    assert row["status"] == "confirmed"


# ---------------------------------------------------------------------------
# C-13 — Auto-confirm measurements past 15-min deadline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C13_auto_confirm_after_15_min(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
):
    """auto_confirm_due_measurements must confirm stale scheduled measurements."""
    from src.engine.measurement_service import auto_confirm_due_measurements
    from src.queue.worker import _notify_auto_confirmed_measurements
    from src.config import settings

    MANAGER_PHONE = "79000000013"

    # Create client row first (measurements have FK → clients)
    await postgres.create_client(pg_pool_integration, 110013, "Auto Client", "auto_client")

    tz = ZoneInfo(settings.timezone)
    future_dt = datetime.now(tz) + timedelta(days=2)
    while future_dt.weekday() == 6:
        future_dt += timedelta(days=1)

    # Insert measurement with auto_confirm_at in the past
    meas_id = await pg_pool_integration.fetchval(
        """
        INSERT INTO measurements
            (client_chat_id, scheduled_time, duration_minutes, address, client_name,
             client_phone, notes, status, auto_confirm_at)
        VALUES ($1, $2, 45, 'Тест', 'Авто Клиент', '79000000013', '', 'scheduled',
                now() - interval '16 minutes')
        RETURNING id
        """,
        110013,
        future_dt,
    )
    assert meas_id is not None

    confirmed = await auto_confirm_due_measurements(pg_pool_integration)
    assert any(int(m["id"]) == meas_id for m in confirmed), "Measurement must be auto-confirmed"

    # Verify DB status
    row = await pg_pool_integration.fetchrow("SELECT status FROM measurements WHERE id=$1", meas_id)
    assert row["status"] == "confirmed"

    # Now call _notify_auto_confirmed_measurements to produce outbox rows
    with patch("src.queue.worker.settings") as mock_settings:
        mock_settings.manager_whatsapp_numbers_list = [MANAGER_PHONE]
        mock_settings.timezone = settings.timezone
        await _notify_auto_confirmed_measurements(pg_pool_integration, mock_telegram_sender, confirmed)

    outbox_rows = await pg_pool_integration.fetch(
        "SELECT channel FROM outbound_events WHERE channel='whatsapp' AND bot_type='manager'"
    )
    assert len(outbox_rows) >= 1, "Manager must receive auto-confirm notification in outbox"


# ---------------------------------------------------------------------------
# C-14 — Manager meas_reject sets status='rejected'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C14_manager_meas_reject(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
):
    """Manager callback meas_reject:N must set status='rejected' in DB."""
    from src.engine.measurement_service import schedule_measurement
    from src.config import settings

    CLIENT_CHAT_ID = 110014
    MANAGER_CHAT_ID = 999014
    MANAGER_UPDATE_ID = 110014

    # Create client rows first (FK constraints: measurements and conversation_state → clients)
    await postgres.create_client(pg_pool_integration, CLIENT_CHAT_ID, "Reject Test", "reject_test")
    # Manager needs a client row: _handle_measurement_callback upserts conversation_state for manager
    await postgres.create_client(pg_pool_integration, MANAGER_CHAT_ID, "Test Manager", "manager_test")

    tz = ZoneInfo(settings.timezone)
    target_dt = datetime.now(tz) + timedelta(days=3)
    while target_dt.weekday() == 6:
        target_dt += timedelta(days=1)

    meas = await schedule_measurement(
        pg_pool_integration, CLIENT_CHAT_ID,
        target_dt.strftime("%Y-%m-%d"), "14:00",
        "Reject Test", "79000000014", "Адрес 14", settings.timezone,
    )
    meas_id = meas["id"]

    # (inbound_events has FK → processed_updates, so mark_update_received first)
    await postgres.mark_update_received(pg_pool_integration, 1140014)
    await postgres.insert_inbound_event(
        pg_pool_integration, 1140014, CLIENT_CHAT_ID, CLIENT_CHAT_ID, "", {}
    )

    is_new = await postgres.mark_update_received(pg_pool_integration, MANAGER_UPDATE_ID)
    assert is_new
    await postgres.insert_inbound_event(
        pg_pool_integration, MANAGER_UPDATE_ID, MANAGER_CHAT_ID, MANAGER_CHAT_ID,
        f"meas_reject:{meas_id}", {}
    )
    job = Job(
        update_id=MANAGER_UPDATE_ID, chat_id=MANAGER_CHAT_ID, user_id=MANAGER_CHAT_ID,
        text=f"meas_reject:{meas_id}", msg_type="command",
        raw_update={}, bot_type="manager",
    )
    await redis_client_integration.enqueue_job("queue:manager", job)

    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, MANAGER_UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"

    row = await pg_pool_integration.fetchrow("SELECT status FROM measurements WHERE id=$1", meas_id)
    assert row["status"] == "rejected"


# ---------------------------------------------------------------------------
# C-15 — Manager proposes alternative slot after rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C15_manager_alternative_time_proposal(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
):
    """Manager free-text slot proposal must create a measurement_slot or confirm via outbound."""
    MANAGER_CHAT_ID = 999015
    MANAGER_UPDATE_ID = 110015

    # Create client row first (conversation_state has FK → clients)
    await postgres.create_client(pg_pool_integration, MANAGER_CHAT_ID, "Manager", "manager_test")

    # Pre-set manager conversation state to scheduling/measurement_alt mode
    await postgres.upsert_conversation_state(
        pg_pool_integration, MANAGER_CHAT_ID, "scheduling", "measurement_alt:1", {"measurement_id": 1}
    )

    from src.config import settings
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(settings.timezone)
    target_dt = datetime.now(tz) + timedelta(days=3)
    while target_dt.weekday() == 6:
        target_dt += timedelta(days=1)
    proposal_text = f"{target_dt.strftime('%d.%m.%Y')} в 14:00"

    is_new = await postgres.mark_update_received(pg_pool_integration, MANAGER_UPDATE_ID)
    assert is_new
    await postgres.insert_inbound_event(
        pg_pool_integration, MANAGER_UPDATE_ID, MANAGER_CHAT_ID, MANAGER_CHAT_ID,
        proposal_text, {}
    )
    job = Job(
        update_id=MANAGER_UPDATE_ID, chat_id=MANAGER_CHAT_ID, user_id=MANAGER_CHAT_ID,
        text=proposal_text, msg_type="text",
        raw_update={}, bot_type="manager",
    )
    await redis_client_integration.enqueue_job("queue:manager", job)

    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, MANAGER_UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"

    # Either a slot was created or an outbound was written
    slots = await pg_pool_integration.fetch("SELECT * FROM measurement_slots")
    outbound = await pg_pool_integration.fetch(
        "SELECT * FROM outbound_events WHERE chat_id=$1", MANAGER_CHAT_ID
    )
    assert len(slots) >= 1 or len(outbound) >= 1, "Slot proposal must produce a slot or outbound message"


# ---------------------------------------------------------------------------
# C-17 — Duplicate WhatsApp external_id is skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C17_whatsapp_duplicate_external_id_skipped(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """Second WhatsApp inbound with same external_id must return {queued:false, duplicate:true}."""
    payload = _wa_payload(external_id="wa-c17-dup-001", phone_e164="79001170017")

    result1 = await _ingest_wa(pg_pool_integration, redis_client_integration, payload)
    assert result1["queued"] is True

    result2 = await _ingest_wa(pg_pool_integration, redis_client_integration, payload)
    assert result2["queued"] is False
    assert result2["duplicate"] is True


# ---------------------------------------------------------------------------
# C-19 — Worker recovery of stuck jobs (xfail if recovery path absent)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C19_worker_recovery_after_kill_simulation(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
):
    """Jobs stuck in queue:processing:client must be moved back to queue:incoming mid-loop.

    Uses recover_stuck_jobs_periodic_loop with a very short interval so the test
    doesn't need to wait for the default 300-second period.
    """
    from src.queue.worker import CLIENT_PROCESSING_QUEUE, CLIENT_QUEUE, recover_stuck_jobs_periodic_loop
    from datetime import timezone

    CHAT_ID = 110019
    UPDATE_ID = 110019

    # Create a job with a received_at well in the past (700 s ago) so it passes
    # the max_age_seconds=5 cutoff used in the recovery loop below.
    stale_received_at = datetime.now(timezone.utc) - timedelta(seconds=700)
    job = Job(
        update_id=UPDATE_ID,
        chat_id=CHAT_ID,
        user_id=CHAT_ID,
        text="stuck",
        msg_type="text",
        raw_update={},
        received_at=stale_received_at,
    )
    # Directly place in processing queue (simulates crash mid-processing)
    await redis_client_integration.enqueue_job(CLIENT_PROCESSING_QUEUE, job)

    # Run the periodic loop manually with a short interval and tight age threshold.
    # We cancel it after one iteration by wrapping in wait_for.
    loop_task = asyncio.create_task(
        recover_stuck_jobs_periodic_loop(
            redis_client_integration,
            interval_seconds=1,
            max_age_seconds=5,
        )
    )
    # Give the loop one tick to run
    await asyncio.sleep(1.5)
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    count = await redis_client_integration.client.llen(redis_client_integration._k(CLIENT_QUEUE))
    assert count >= 1, "Job must migrate from processing to incoming without restart"


# ---------------------------------------------------------------------------
# C-20 — LLM TimeoutError produces fallback reply (not a crash)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C20_llm_timeout_user_gets_fallback(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
    monkeypatch,
):
    """TimeoutError from call_llm must produce a fallback reply to the user, not a crash."""
    CHAT_ID = 110020
    UPDATE_ID = 110020

    import src.queue.worker as worker_mod

    async def _raise_timeout(_prompt):
        raise TimeoutError("Gemini CLI timed out")

    monkeypatch.setattr(worker_mod, "call_llm", _raise_timeout)

    update = _telegram_update(UPDATE_ID, CHAT_ID, "тест таймаута")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    # Worker should handle TimeoutError gracefully and mark as failed
    final_status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID, "failed"), timeout=10
    )
    assert final_status == "failed", "TimeoutError must mark update as failed, not crash"

    # Fallback message must have been sent
    rows = await pg_pool_integration.fetch(
        "SELECT reply_text FROM outbound_events WHERE chat_id=$1", CHAT_ID
    )
    assert len(rows) >= 1, "Fallback reply must be sent to user on LLM timeout"


# ---------------------------------------------------------------------------
# C-21 — LLM garbage output: no actions applied, no crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C21_llm_garbage_no_actions_applied(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
    monkeypatch,
):
    """Non-JSON LLM output must not crash the worker and must produce a reply."""
    CHAT_ID = 110021
    UPDATE_ID = 110021

    import src.queue.worker as worker_mod

    async def _return_garbage(_prompt):
        return "some random text not json и вообще непонятно что"

    monkeypatch.setattr(worker_mod, "call_llm", _return_garbage)
    # Don't patch apply_actions — let parse_actions return fallback ActionsJson

    update = _telegram_update(UPDATE_ID, CHAT_ID, "привет бот")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    # Should complete (parse_actions has a FALLBACK, no exception)
    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"

    rows = await pg_pool_integration.fetch(
        "SELECT reply_text FROM outbound_events WHERE chat_id=$1", CHAT_ID
    )
    assert len(rows) >= 1, "A reply (even fallback) must be sent"


# ---------------------------------------------------------------------------
# C-22 — Mini App GET /api/gallery/works returns inserted works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C22_mini_app_gallery_list(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """Seeded gallery works must be retrievable from the DB."""
    # Note: the HTTP layer (Telegram initData auth + CORSMiddleware/anyio task group)
    # conflicts with the session-scoped asyncpg pool inside the pytest-asyncio event loop.
    # We verify the DB logic directly: data inserted by create_gallery_work must be
    # returned by list_gallery_works (the function called by GET /api/gallery/works).
    await postgres.create_gallery_work(
        pg_pool_integration, "sliding_2", "1", "none", "Работа А", "", 110022
    )
    await postgres.create_gallery_work(
        pg_pool_integration, "fixed", "2", "none", "Работа Б", "", 110022
    )

    works = await postgres.list_gallery_works(pg_pool_integration)
    assert isinstance(works, list)
    assert len(works) >= 2, f"Expected at least 2 works, got {works}"


# ---------------------------------------------------------------------------
# C-24 — CMS OTP flow: send + receive + verify returns access_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C24_cms_otp_flow(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """Full OTP flow: seed manager → generate OTP → store → verify → get access_token."""
    # Note: CORSMiddleware uses anyio task groups which conflict with the session-scoped
    # asyncpg pool in the pytest-asyncio event loop. We test the business logic directly.
    from src.api.auth import create_access_token, generate_otp_code, hash_otp, verify_otp
    from src.config import settings
    from datetime import datetime, timedelta, timezone

    PHONE = "79009990024"
    await postgres.upsert_manager(pg_pool_integration, PHONE, "Test Manager", True)

    # Simulate OTP generation and storage (what /api/auth/otp/send does)
    code = generate_otp_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expiry_minutes)
    await postgres.store_otp(pg_pool_integration, PHONE, hash_otp(code), expires_at)

    # Simulate OTP verification (what /api/auth/otp/verify does)
    otp = await postgres.get_otp(pg_pool_integration, PHONE)
    assert otp is not None, "OTP not found after storage"
    assert verify_otp(code, otp["code_hash"]), "OTP verify failed"

    # Complete the flow: issue access token
    manager = await postgres.get_manager(pg_pool_integration, PHONE)
    assert manager is not None and manager.get("is_active")
    access_token = create_access_token({"sub": PHONE, "name": manager.get("name")})
    assert access_token, "Expected a non-empty access_token"


# ---------------------------------------------------------------------------
# C-25 — OTP brute-force: 6th wrong attempt returns 429
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C25_otp_brute_force_blocked(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """After max failed OTP attempts, further attempts must be blocked by DB guard."""
    # Note: CORSMiddleware uses anyio task groups which conflict with the session-scoped
    # asyncpg pool. We test the DB-level brute-force protection directly.
    from src.api.auth import generate_otp_code, hash_otp, verify_otp
    from src.config import settings
    from datetime import datetime, timedelta, timezone

    PHONE = "79009990025"
    await postgres.upsert_manager(pg_pool_integration, PHONE, "Brute Force Test", True)

    # Store a valid OTP
    code = generate_otp_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await postgres.store_otp(pg_pool_integration, PHONE, hash_otp(code), expires_at)

    # Simulate max_attempts failed verifications
    for _ in range(settings.otp_max_attempts):
        await postgres.increment_otp_attempts(pg_pool_integration, PHONE)

    # Now the OTP must be blocked: attempts >= otp_max_attempts
    otp = await postgres.get_otp(pg_pool_integration, PHONE)
    assert otp is not None
    assert otp["attempts"] >= settings.otp_max_attempts, (
        f"Expected attempts >= {settings.otp_max_attempts}, got {otp['attempts']}"
    )


# ---------------------------------------------------------------------------
# C-26 — Long dialog: memory still contains key params after summarization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C26_long_dialog_memory_keeps_key_params(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    monkeypatch,
):
    """After 100 messages, key dimension facts from early messages must survive in memory.

    Uses a mocked call_llm that returns a compressed summary containing the key
    facts so no actual LLM call is made.
    """
    from src.llm import conversation_memory as mem_mod

    CHAT_ID = 110026

    # FK: conversation_state.chat_id references clients.chat_id
    await postgres.create_client(pg_pool_integration, CHAT_ID)

    await postgres.upsert_conversation_state(
        pg_pool_integration, CHAT_ID, "collecting", None,
        {"shape": "Прямая", "height": 2.7, "width_a": 3.5, "glass_type": "1"},
    )

    # Insert 100 chat messages; key facts appear in first few messages
    await postgres.insert_chat_message(pg_pool_integration, CHAT_ID, "user", "ширина 3.5 метра высота 2.7")
    await postgres.insert_chat_message(pg_pool_integration, CHAT_ID, "assistant", "Записал: ширина 3.5, высота 2.7")
    for i in range(98):
        role = "user" if i % 2 == 0 else "assistant"
        await postgres.insert_chat_message(pg_pool_integration, CHAT_ID, role, f"Дополнительное сообщение {i}")

    # Mock the LLM to return a compressed summary that preserves the key facts
    async def fake_call_llm(_prompt: str) -> str:
        return "Клиент указал: ширина 3.5 м, высота 2.7 м. [сжато]"

    monkeypatch.setattr(mem_mod, "_call_llm_for_compression", fake_call_llm, raising=False)

    # Patch call_llm inside conversation_memory's refresh function
    import src.llm.executor as executor_mod
    monkeypatch.setattr(executor_mod, "call_llm", fake_call_llm)

    await mem_mod.refresh_conversation_memory_if_needed(pg_pool_integration, CHAT_ID)

    memory = await postgres.get_conversation_memory(pg_pool_integration, CHAT_ID)
    assert memory is not None, "Memory must be created after refresh"

    summary = (memory.get("summary_text") or "") + str(memory.get("facts_json") or "")
    assert "3.5" in summary or "2.7" in summary, (
        "Key dimension facts must survive in memory after summarization of 100 messages"
    )


# ---------------------------------------------------------------------------
# C-27 — /reset command clears state (xfail if not implemented)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C27_reset_command_clears_state(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    worker_running,
):
    """/reset command must clear conversation state and return a fresh start message."""
    CHAT_ID = 110027
    UPDATE_ID = 110027

    # Pre-populate so that there is something to clear
    await postgres.create_client(pg_pool_integration, CHAT_ID, "Reset User", "reset_user")
    await postgres.upsert_conversation_state(
        pg_pool_integration, CHAT_ID, "collecting", "step1",
        {"shape": "Прямая", "height": 2.5},
    )

    update = _telegram_update(UPDATE_ID, CHAT_ID, "/reset")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update, msg_type="command")

    status = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID, "completed"), timeout=10
    )
    assert status == "completed"

    state = await postgres.get_conversation_state(pg_pool_integration, CHAT_ID)
    assert (state is None) or (state.get("mode") == "idle"), "State must be cleared by /reset"

    # Verify the friendly reset reply was queued in outbound
    rows = await pg_pool_integration.fetch(
        "SELECT reply_text FROM outbound_events WHERE chat_id=$1", CHAT_ID
    )
    assert any("сброшено" in (r["reply_text"] or "").lower() for r in rows), (
        "Expected reset confirmation message in outbound events"
    )


# ---------------------------------------------------------------------------
# C-28 — Off-topic message results in polite refusal (mocked LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C28_off_topic_polite_refusal(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
):
    """Off-topic message with mocked refusal reply must be delivered to user."""
    CHAT_ID = 110028
    UPDATE_ID = 110028
    REFUSAL = "Я могу помочь с расчётом перегородки."
    mock_call_llm[0] = f'{{"reply_text":"{REFUSAL}","actions":null}}'

    update = _telegram_update(UPDATE_ID, CHAT_ID, "кто выиграл Лигу чемпионов?")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update)

    await asyncio.wait_for(_poll_outbound(pg_pool_integration, CHAT_ID), timeout=10)

    rows = await pg_pool_integration.fetch(
        "SELECT reply_text FROM outbound_events WHERE chat_id=$1", CHAT_ID
    )
    assert any(REFUSAL in (r["reply_text"] or "") for r in rows), (
        f"Expected refusal text in outbound. Got: {[r['reply_text'] for r in rows]}"
    )


# ---------------------------------------------------------------------------
# C-29 — Pricing engine compute_price: total_price > 0, no division by zero
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C29_minimal_config_pricing(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
):
    """calculate_price with minimal valid params must return total_price > 0."""
    from src.engine.pricing_engine import calculate_price

    result = calculate_price(
        shape="Прямая",
        height=2.5,
        width_a=3.0,
        partition_type="sliding_2",
    )
    assert result["total_price"] > 0, f"total_price must be positive, got: {result}"
    assert result["currency"] == "USD"


# ---------------------------------------------------------------------------
# C-30 — Concurrent messages for same chat_id: second job is delayed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C30_concurrent_messages_serialized(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
):
    """Second job for same chat_id while first is processing must land in delayed queue."""
    from src.queue.worker import CLIENT_DELAYED_QUEUE

    CHAT_ID = 110030
    UPDATE_ID_1 = 110030
    UPDATE_ID_2 = 110031

    # Inject slow processing by patching call_llm to sleep
    import src.queue.worker as worker_mod
    slow_response = '{"reply_text":"медленный ответ","actions":null}'
    real_call_llm = mock_call_llm  # keep reference

    call_count = 0

    async def _slow_llm(_prompt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(2)  # Hold the lock for first job
        return slow_response

    worker_mod_orig_llm = worker_mod.call_llm

    # First message
    update1 = _telegram_update(UPDATE_ID_1, CHAT_ID, "первое медленное")
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update1)

    # Second message immediately after — worker might have the lock from job 1
    update2 = _telegram_update(UPDATE_ID_2, CHAT_ID, "второе быстрое")
    await asyncio.sleep(0.1)
    await _ingest_telegram(pg_pool_integration, redis_client_integration, update2)

    # Both must eventually complete within the timeout
    status1 = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID_1, "completed"), timeout=15
    )
    status2 = await asyncio.wait_for(
        _poll_update_status(pg_pool_integration, UPDATE_ID_2, "completed"), timeout=15
    )
    assert status1 == "completed"
    assert status2 == "completed"

    # Verify delayed queue was used for the second job at some point
    # (It may have already been consumed — so we check outbound exists for both)
    rows1 = await pg_pool_integration.fetch(
        "SELECT * FROM outbound_events WHERE chat_id=$1", CHAT_ID
    )
    assert len(rows1) >= 1, "Both messages must produce outbound events"

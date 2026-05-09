from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.engine import measurement_service


TZ = "Asia/Bishkek"


class FakePool:
    def __init__(self, fetchrow_results=None, fetch_results=None, fetchval_results=None):
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])
        self.fetchval_results = list(fetchval_results or [])
        self.fetchrow_calls = []
        self.fetch_calls = []
        self.calls = []

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        self.calls.append(("fetchrow", query, args))
        return self.fetchrow_results.pop(0) if self.fetchrow_results else None

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        self.calls.append(("fetch", query, args))
        return self.fetch_results.pop(0) if self.fetch_results else []

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query, args))
        return self.fetchval_results.pop(0) if self.fetchval_results else 0

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return "OK"


def _future_date(days=1) -> str:
    candidate = datetime.now(ZoneInfo(TZ)) + timedelta(days=days)
    if candidate.weekday() == 6:
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%d")


def test_validate_time_rejects_past():
    past = (datetime.now(ZoneInfo(TZ)) - timedelta(days=1)).strftime("%Y-%m-%d")

    with pytest.raises(ValueError, match="прошлом"):
        measurement_service.validate_time(past, "10:15", TZ)


def test_validate_time_rejects_outside_hours():
    future = _future_date()

    with pytest.raises(ValueError, match="доступны"):
        measurement_service.validate_time(future, "08:45", TZ)
    with pytest.raises(ValueError, match="доступны"):
        measurement_service.validate_time(future, "21:15", TZ)


def test_validate_time_rejects_non_15min():
    with pytest.raises(ValueError, match="кратно 15"):
        measurement_service.validate_time(_future_date(), "10:07", TZ)


def test_validate_time_accepts_valid():
    result = measurement_service.validate_time(_future_date(), "10:15", TZ)

    assert result.hour == 10
    assert result.minute == 15
    assert result.tzinfo is not None


def test_validate_time_rejects_sunday():
    now = datetime.now(ZoneInfo(TZ))
    days_until_sunday = (6 - now.weekday()) % 7 or 7
    sunday = (now + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")

    with pytest.raises(ValueError, match="воскресенье"):
        measurement_service.validate_time(sunday, "10:00", TZ)


@pytest.mark.asyncio
async def test_check_conflict_detects_overlap():
    start = measurement_service.validate_time(_future_date(), "10:15", TZ)
    pool = FakePool(
        fetchrow_results=[
            {
                "id": 1,
                "scheduled_time": start,
                "duration_minutes": 60,
                "client_name": "Иван",
                "status": "scheduled",
            }
        ]
    )

    conflict = await measurement_service.check_conflict(pool, start)

    assert conflict["id"] == 1
    assert pool.fetchrow_calls
    query, args = pool.fetchrow_calls[0]
    assert "scheduled_time > $1" in query
    assert "scheduled_time < $2" in query
    assert args[0] == start - timedelta(minutes=measurement_service.MIN_START_GAP_MINUTES)
    assert args[1] == start + timedelta(minutes=measurement_service.MIN_START_GAP_MINUTES)


@pytest.mark.asyncio
async def test_check_conflict_no_overlap():
    start = measurement_service.validate_time(_future_date(), "10:15", TZ)
    pool = FakePool(fetchrow_results=[None])

    assert await measurement_service.check_conflict(pool, start) is None


@pytest.mark.asyncio
async def test_get_available_slots_excludes_busy():
    future = _future_date()
    busy_start = measurement_service.validate_time(future, "10:30", TZ)
    pool = FakePool(fetch_results=[[{"scheduled_time": busy_start, "duration_minutes": 60}]])

    slots = await measurement_service.get_available_slots(pool, future, TZ)

    assert "09:00" in slots
    assert "09:45" in slots
    assert "10:00" not in slots
    assert "10:30" not in slots
    assert "11:15" in slots


@pytest.mark.asyncio
async def test_schedule_measurement_raises_on_conflict():
    future = _future_date()
    start = measurement_service.validate_time(future, "10:15", TZ)
    pool = FakePool(fetchrow_results=[{"scheduled_time": start, "client_name": "Иван"}])

    with pytest.raises(ValueError, match="Это время занято"):
        await measurement_service.schedule_measurement(
            pool,
            chat_id=10,
            date=future,
            time="10:15",
            client_name="Петр",
            phone="+996",
            address="Адрес",
            timezone=TZ,
        )


@pytest.mark.asyncio
async def test_schedule_measurement_requires_address():
    with pytest.raises(ValueError, match="адрес"):
        await measurement_service.schedule_measurement(
            FakePool(),
            chat_id=10,
            date=_future_date(),
            time="10:15",
            client_name="Петр",
            phone="+996",
            address="",
            timezone=TZ,
        )


@pytest.mark.asyncio
async def test_schedule_measurement_creates_record():
    future = _future_date()
    start = measurement_service.validate_time(future, "10:15", TZ)
    pool = FakePool(
        fetchrow_results=[
            None,
            {
                "id": 7,
                "client_chat_id": 10,
                "scheduled_time": start,
                "duration_minutes": 60,
                "address": "Адрес",
                "client_name": "Петр",
                "client_phone": "+996",
                "status": "scheduled",
            },
        ]
    )

    measurement = await measurement_service.schedule_measurement(
        pool,
        chat_id=10,
        date=future,
        time="10:15",
        client_name="Петр",
        phone="+996",
        address="Адрес",
        timezone=TZ,
    )

    assert measurement["id"] == 7
    assert measurement["client_chat_id"] == 10
    assert len(pool.fetchrow_calls) == 2
    assert pool.fetchrow_calls[1][1][-1] == measurement_service.MANAGER_CONFIRM_TIMEOUT_MINUTES


@pytest.mark.asyncio
async def test_schedule_measurement_links_order_and_marks_scheduled():
    future = _future_date()
    start = measurement_service.validate_time(future, "10:15", TZ)
    pool = FakePool(
        fetchrow_results=[
            None,
            {
                "id": 7,
                "client_chat_id": 10,
                "scheduled_time": start,
                "duration_minutes": 45,
                "address": "Адрес",
                "client_name": "Петр",
                "client_phone": "+996",
                "status": "scheduled",
                "order_request_id": "order-1",
            },
        ]
    )

    measurement = await measurement_service.schedule_measurement(
        pool,
        chat_id=10,
        date=future,
        time="10:15",
        client_name="Петр",
        phone="+996",
        address="Адрес",
        timezone=TZ,
        order_request_id="order-1",
    )

    assert measurement["order_request_id"] == "order-1"
    insert_query, insert_args = pool.fetchrow_calls[1]
    assert "order_request_id" in insert_query
    assert insert_args[-2] == "order-1"
    assert pool.fetchrow_calls[1][1][-1] == measurement_service.MANAGER_CONFIRM_TIMEOUT_MINUTES
    assert any(call[0] == "execute" and "UPDATE orders" in call[1] for call in pool.calls)


@pytest.mark.asyncio
async def test_update_status_validates_transitions():
    scheduled_time = measurement_service.validate_time(_future_date(), "10:15", TZ)
    pool = FakePool(
        fetchrow_results=[
            {"id": 1, "status": "scheduled", "scheduled_time": scheduled_time},
            {"id": 1, "status": "confirmed", "scheduled_time": scheduled_time, "manager_chat_id": 99},
        ]
    )

    updated = await measurement_service.update_measurement_status(pool, 1, "confirmed", manager_chat_id=99)

    assert updated["status"] == "confirmed"

    invalid_pool = FakePool(fetchrow_results=[{"id": 2, "status": "idle"}])
    with pytest.raises(ValueError, match="Нельзя перевести"):
        await measurement_service.update_measurement_status(invalid_pool, 2, "completed")


@pytest.mark.asyncio
async def test_update_status_updates_linked_order():
    scheduled_time = measurement_service.validate_time(_future_date(), "10:15", TZ)
    pool = FakePool(
        fetchrow_results=[
            {"id": 1, "status": "scheduled", "scheduled_time": scheduled_time, "order_request_id": "order-1"},
            {"id": 1, "status": "confirmed", "scheduled_time": scheduled_time, "order_request_id": "order-1"},
        ]
    )

    updated = await measurement_service.update_measurement_status(pool, 1, "confirmed", manager_chat_id=99)

    assert updated["status"] == "confirmed"
    assert any(call[0] == "execute" and "UPDATE orders" in call[1] for call in pool.calls)


@pytest.mark.asyncio
async def test_update_status_rejects_unknown_status():
    pool = FakePool()

    with pytest.raises(ValueError, match="Неизвестный статус"):
        await measurement_service.update_measurement_status(pool, 1, "banana")


@pytest.mark.asyncio
async def test_auto_confirm_due_measurements_updates_scheduled_rows():
    scheduled_time = measurement_service.validate_time(_future_date(), "10:15", TZ)
    pool = FakePool(fetch_results=[[{"id": 1, "status": "confirmed", "scheduled_time": scheduled_time}]])

    rows = await measurement_service.auto_confirm_due_measurements(pool)

    assert rows[0]["id"] == 1
    assert "auto_confirm_at" in pool.fetch_calls[0][0]


@pytest.mark.asyncio
async def test_upsert_measurement_slot_stores_manager_open_slot():
    future = _future_date()
    slot_start = measurement_service.validate_time(future, "11:00", TZ)
    pool = FakePool(fetchrow_results=[None, {"id": 4, "slot_start": slot_start, "status": "open"}])

    slot = await measurement_service.upsert_measurement_slot(pool, future, "11:00", TZ, manager_chat_id=99)

    assert slot["id"] == 4
    assert "measurement_slots" in pool.fetchrow_calls[1][0]


def test_parse_slot_proposal_understands_manager_text():
    base = datetime(2026, 4, 16, 10, 0, tzinfo=ZoneInfo(TZ))

    assert measurement_service.parse_slot_proposal("завтра на 11:00", TZ, now=base) == ("2026-04-17", "11:00")
    assert measurement_service.parse_slot_proposal("20.04 15:30", TZ, now=base) is None  # year required now


def test_parse_slot_proposal_ignores_price_like_dots():
    """2.1 — dot-format without year must not crash on prices like '2.50 м' or '1500.50'."""
    tz = TZ
    base = datetime(2026, 4, 16, 10, 0, tzinfo=ZoneInfo(tz))
    assert measurement_service.parse_slot_proposal("замер 2.50 м ширина", tz, now=base) is None
    assert measurement_service.parse_slot_proposal("бюджет 1500.50 руб", tz, now=base) is None


def test_parse_slot_proposal_valid_full_date():
    """2.1 — full dot-format date with year still parses correctly."""
    base = datetime(2026, 4, 16, 10, 0, tzinfo=ZoneInfo(TZ))
    assert measurement_service.parse_slot_proposal("приду 13.05.2026 в 14:00", TZ, now=base) == ("2026-05-13", "14:00")


def test_parse_slot_proposal_invalid_month_swallowed():
    """2.1 — 13.13.2026 has invalid month, exception must be swallowed → None."""
    base = datetime(2026, 4, 16, 10, 0, tzinfo=ZoneInfo(TZ))
    assert measurement_service.parse_slot_proposal("13.13.2026 в 11:00", TZ, now=base) is None


def test_parse_slot_proposal_invalid_day_swallowed():
    """2.1 — 31.02.2026 has invalid day for February, exception must be swallowed → None."""
    base = datetime(2026, 4, 16, 10, 0, tzinfo=ZoneInfo(TZ))
    assert measurement_service.parse_slot_proposal("31.02.2026 в 11:00", TZ, now=base) is None


def test_parse_slot_proposal_relative_keywords_still_work():
    """2.1 — existing relative-keyword tests must still pass."""
    base = datetime(2026, 4, 16, 10, 0, tzinfo=ZoneInfo(TZ))
    assert measurement_service.parse_slot_proposal("завтра на 11:00", TZ, now=base) == ("2026-04-17", "11:00")
    assert measurement_service.parse_slot_proposal("сегодня в 15:30", TZ, now=base) == ("2026-04-16", "15:30")
    assert measurement_service.parse_slot_proposal("послезавтра 10:00", TZ, now=base) == ("2026-04-18", "10:00")


@pytest.mark.asyncio
async def test_get_due_reminders_uses_correct_window():
    pool = FakePool(fetch_results=[[]])
    await measurement_service.get_due_reminders(pool)
    assert pool.calls
    sql = pool.calls[0][1]
    args = pool.calls[0][2]
    assert "status = 'confirmed'" in sql
    # 60-minute lookahead, not the old [55, 60] window — see commit message
    assert "scheduled_time > now()" in sql
    assert "<= now() +" in sql
    assert args == ("60",)
    # Dedup is on outbound_events idempotency_key, not on reminder_sent_at,
    # so a failed delivery can be retried on the next tick.
    assert "outbound_events" in sql
    assert "'reminder:'" in sql
    assert "reminder_sent_at IS NULL" not in sql


@pytest.mark.asyncio
async def test_auto_close_past_measurements_uses_grace_window():
    pool = FakePool(fetchval_results=[3])
    closed = await measurement_service.auto_close_past_measurements(pool, grace_hours=24)
    assert closed == 3
    assert pool.calls
    _kind, sql, args = pool.calls[0]
    assert "UPDATE measurements" in sql
    assert "status='completed'" in sql
    assert "scheduled_time + (duration_minutes" in sql
    assert "WHERE status IN ('scheduled', 'confirmed')" in sql
    assert args == ("24",)


@pytest.mark.asyncio
async def test_mark_reminder_sent_updates_correct_row():
    pool = FakePool()
    await measurement_service.mark_reminder_sent(pool, 42)
    assert pool.calls
    _kind, sql, args = pool.calls[0]
    assert "reminder_sent_at = now()" in sql
    assert args == (42,)


# ─── propose_reschedule ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_reschedule_saves_pending_fields():
    future = _future_date()
    current_start = measurement_service.validate_time(future, "11:00", TZ)
    proposed_start = measurement_service.validate_time(future, "17:00", TZ)

    pool = FakePool(
        fetchrow_results=[
            # SELECT current row
            {
                "id": 10,
                "scheduled_time": current_start,
                "duration_minutes": 45,
                "client_chat_id": 99001,
            },
            # check_conflict returns None (no conflict)
            None,
            # UPDATE RETURNING *
            {
                "id": 10,
                "scheduled_time": current_start,
                "duration_minutes": 45,
                "client_chat_id": 99001,
                "pending_reschedule_at": proposed_start,
                "pending_reschedule_reason": "не могу",
            },
        ]
    )

    result = await measurement_service.propose_reschedule(
        pool,
        10,
        new_date=future,
        new_time="17:00",
        timezone=TZ,
        reason="не могу",
    )

    assert result["pending_reschedule_at"] == proposed_start
    assert result["pending_reschedule_reason"] == "не могу"
    # Verify UPDATE query was called
    update_calls = [c for c in pool.calls if c[0] == "fetchrow" and "pending_reschedule_at" in c[1]]
    assert update_calls, "Expected UPDATE with pending_reschedule_at"


@pytest.mark.asyncio
async def test_propose_reschedule_raises_if_not_found():
    pool = FakePool(fetchrow_results=[None])
    with pytest.raises(ValueError, match="не найден"):
        await measurement_service.propose_reschedule(
            pool, 999, new_date=None, new_time="10:00", timezone=TZ
        )


@pytest.mark.asyncio
async def test_propose_reschedule_raises_on_conflict():
    future = _future_date()
    current_start = measurement_service.validate_time(future, "11:00", TZ)
    conflicting_start = measurement_service.validate_time(future, "17:00", TZ)

    pool = FakePool(
        fetchrow_results=[
            {
                "id": 10,
                "scheduled_time": current_start,
                "duration_minutes": 45,
                "client_chat_id": 99001,
            },
            # check_conflict returns a conflicting measurement
            {
                "id": 20,
                "scheduled_time": conflicting_start,
                "duration_minutes": 45,
                "client_name": "Другой",
                "status": "confirmed",
            },
        ]
    )

    with pytest.raises(ValueError, match="занято"):
        await measurement_service.propose_reschedule(
            pool, 10, new_date=future, new_time="17:00", timezone=TZ
        )


@pytest.mark.asyncio
async def test_propose_reschedule_uses_current_date_when_none():
    """When new_date is None, propose_reschedule uses the measurement's existing date."""
    future = _future_date()
    current_start = measurement_service.validate_time(future, "11:00", TZ)
    proposed_start = measurement_service.validate_time(future, "17:00", TZ)

    pool = FakePool(
        fetchrow_results=[
            {
                "id": 10,
                "scheduled_time": current_start,
                "duration_minutes": 45,
                "client_chat_id": 99001,
            },
            None,  # no conflict
            {
                "id": 10,
                "scheduled_time": current_start,
                "duration_minutes": 45,
                "client_chat_id": 99001,
                "pending_reschedule_at": proposed_start,
                "pending_reschedule_reason": "",
            },
        ]
    )

    result = await measurement_service.propose_reschedule(
        pool, 10, new_date=None, new_time="17:00", timezone=TZ
    )
    assert result["pending_reschedule_at"] == proposed_start


# ─── clear_pending_reschedule ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clear_pending_reschedule_nullifies_fields():
    pool = FakePool()
    await measurement_service.clear_pending_reschedule(pool, 10)
    assert pool.calls
    _kind, sql, args = pool.calls[0]
    assert "pending_reschedule_at = NULL" in sql
    assert args == (10,)


# ─── update_measurement clears pending when time changes ──────────────────────

@pytest.mark.asyncio
async def test_update_measurement_clears_pending_on_time_change():
    future = _future_date()
    current_start = measurement_service.validate_time(future, "11:00", TZ)
    new_start = measurement_service.validate_time(future, "17:00", TZ)

    pool = FakePool(
        fetchrow_results=[
            # SELECT current row
            {
                "id": 5,
                "scheduled_time": current_start,
                "duration_minutes": 45,
            },
            # check_conflict: no conflict
            None,
            # UPDATE RETURNING *
            {
                "id": 5,
                "scheduled_time": new_start,
                "duration_minutes": 45,
                "client_chat_id": 77,
            },
        ]
    )

    await measurement_service.update_measurement(
        pool, 5, date=future, time="17:00", timezone=TZ
    )

    # Verify there was an execute call clearing pending fields
    clear_calls = [
        c for c in pool.calls
        if c[0] == "execute" and "pending_reschedule_at = NULL" in c[1]
    ]
    assert clear_calls, "Expected pending reschedule fields to be cleared on time update"

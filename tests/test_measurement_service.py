from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.engine import measurement_service


TZ = "Asia/Bishkek"


class FakePool:
    def __init__(self, fetchrow_results=None, fetch_results=None):
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])
        self.fetchrow_calls = []
        self.fetch_calls = []

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        return self.fetchrow_results.pop(0) if self.fetchrow_results else None

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        return self.fetch_results.pop(0) if self.fetch_results else []


def _future_date(days=1) -> str:
    return (datetime.now(ZoneInfo(TZ)) + timedelta(days=days)).strftime("%Y-%m-%d")


def test_validate_time_rejects_past():
    past = (datetime.now(ZoneInfo(TZ)) - timedelta(days=1)).strftime("%Y-%m-%d")

    with pytest.raises(ValueError, match="прошлом"):
        measurement_service.validate_time(past, "10:15", TZ)


def test_validate_time_rejects_outside_hours():
    future = _future_date()

    with pytest.raises(ValueError, match="доступны"):
        measurement_service.validate_time(future, "09:00", TZ)
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

    assert "09:30" in slots
    assert "10:00" not in slots
    assert "10:30" not in slots
    assert "11:00" not in slots
    assert "11:30" in slots


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
async def test_update_status_rejects_unknown_status():
    pool = FakePool()

    with pytest.raises(ValueError, match="Неизвестный статус"):
        await measurement_service.update_measurement_status(pool, 1, "banana")

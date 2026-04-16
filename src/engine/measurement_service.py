"""Measurement scheduling service — no external calendar dependency.

All data lives in PostgreSQL. Handles:
- Time validation (business hours, 15-min alignment, not in past)
- Conflict detection (active measurement starts must be at least 45 minutes apart)
- Available slots query (for Gemini prompt context)
- Full status lifecycle: scheduled → confirmed/rejected/cancelled/completed
- Manager and client notifications via Telegram
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.db import postgres
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Business hours
OPENING_HOUR, OPENING_MINUTE = 9, 0
CLOSING_HOUR, CLOSING_MINUTE = 19, 0
DEFAULT_DURATION_MINUTES = 45
MAX_DAYS_AHEAD = 14
SLOT_STEP_MINUTES = 15
MIN_START_GAP_MINUTES = 45
MANAGER_CONFIRM_TIMEOUT_MINUTES = 15

VALID_STATUSES = {"scheduled", "confirmed", "rejected", "cancelled", "completed", "rescheduled"}
ACTIVE_STATUSES = {"scheduled", "confirmed"}

# Status transitions
ALLOWED_TRANSITIONS = {
    "scheduled": {"confirmed", "rejected", "cancelled", "rescheduled"},
    "confirmed": {"completed", "cancelled", "rescheduled"},
}


def validate_time(date: str, time: str, timezone: str) -> datetime:
    """Validate and return measurement datetime."""
    tz = ZoneInfo(timezone)
    start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)

    if start.minute % 15 != 0:
        raise ValueError("Время замера должно быть кратно 15 минутам (например 10:00, 10:15, 10:30)")

    if start.weekday() == 6:
        raise ValueError("В воскресенье замеры не проводятся")

    opening = start.replace(hour=OPENING_HOUR, minute=OPENING_MINUTE, second=0)
    closing = start.replace(hour=CLOSING_HOUR, minute=CLOSING_MINUTE, second=0)
    if start < opening or start > closing:
        raise ValueError(f"Замеры доступны с {OPENING_HOUR}:{OPENING_MINUTE:02d} до {CLOSING_HOUR}:{CLOSING_MINUTE:02d}")

    now = datetime.now(tz)
    if start < now:
        raise ValueError("Нельзя записать замер в прошлом")

    if start > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValueError(f"Запись доступна максимум на {MAX_DAYS_AHEAD} дней вперёд")

    return start


async def check_conflict(pool, start: datetime, duration_minutes: int = DEFAULT_DURATION_MINUTES) -> dict | None:
    """Check if requested start is too close to an existing active measurement.

    Returns the conflicting measurement dict, or None if slot is free.
    """
    row = await pool.fetchrow(
        """
        SELECT id, scheduled_time, duration_minutes, client_name, status
        FROM measurements
        WHERE status IN ('scheduled', 'confirmed')
          AND scheduled_time > $1 - ($2 || ' minutes')::interval
          AND scheduled_time < $1 + ($2 || ' minutes')::interval
        LIMIT 1
        """,
        start,
        MIN_START_GAP_MINUTES,
    )
    return dict(row) if row else None


async def get_available_slots(
    pool,
    date: str,
    timezone: str,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
) -> list[str]:
    """Return available time slots for a given date.

    Used in Gemini prompt context so the model can suggest free times.
    """
    tz = ZoneInfo(timezone)
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
    if day.weekday() == 6:
        return []
    day_start = day.replace(hour=OPENING_HOUR, minute=OPENING_MINUTE, second=0)
    day_end = day_start.replace(hour=CLOSING_HOUR, minute=CLOSING_MINUTE)
    now = datetime.now(tz)

    # Fetch all active measurements for this date
    rows = await pool.fetch(
        """
        SELECT scheduled_time, duration_minutes
        FROM measurements
        WHERE status IN ('scheduled', 'confirmed')
          AND scheduled_time::date = $1::date
        ORDER BY scheduled_time
        """,
        day_start,
    )
    busy_starts = [row["scheduled_time"] for row in rows]

    slots = []
    current = day_start
    while current <= day_end:
        if current > now:  # Don't show past slots
            is_free = all(
                abs((current - busy_start).total_seconds()) >= MIN_START_GAP_MINUTES * 60
                for busy_start in busy_starts
            )
            if is_free:
                slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=SLOT_STEP_MINUTES)

    return slots


async def schedule_measurement(
    pool,
    chat_id: int,
    date: str,
    time: str,
    client_name: str,
    phone: str,
    address: str,
    timezone: str,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
) -> dict[str, Any]:
    """Create a new measurement. Raises ValueError on conflict or invalid time."""
    if not address or not address.strip():
        raise ValueError("Для записи на замер нужен адрес, куда ехать мастеру")

    start = validate_time(date, time, timezone)

    conflict = await check_conflict(pool, start, duration_minutes)
    if conflict:
        conflict_time = conflict["scheduled_time"].strftime("%H:%M")
        raise ValueError(
            f"Это время занято (замер в {conflict_time} для {conflict['client_name']}). "
            f"Выберите другое время."
        )

    row = await pool.fetchrow(
        """
        INSERT INTO measurements
            (client_chat_id, scheduled_time, duration_minutes, address, client_name, client_phone, notes, status, auto_confirm_at)
        VALUES ($1, $2, $3, $4, $5, $6, '', 'scheduled', now() + ($7 || ' minutes')::interval)
        RETURNING *
        """,
        chat_id,
        start,
        duration_minutes,
        address or "",
        client_name,
        phone,
        MANAGER_CONFIRM_TIMEOUT_MINUTES,
    )
    measurement = dict(row)
    logger.info("measurement_created", extra={"id": measurement["id"], "chat_id": chat_id, "time": start.isoformat()})
    return measurement


async def update_measurement_status(
    pool,
    measurement_id: int,
    new_status: str,
    manager_chat_id: int | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Transition measurement status. Validates allowed transitions."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Неизвестный статус: {new_status}")

    current = await pool.fetchrow("SELECT * FROM measurements WHERE id=$1", measurement_id)
    if not current:
        raise ValueError(f"Замер #{measurement_id} не найден")

    current_status = current["status"]
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise ValueError(f"Нельзя перевести замер из '{current_status}' в '{new_status}'")

    row = await pool.fetchrow(
        """
        UPDATE measurements
        SET status=$2, manager_chat_id=COALESCE($3, manager_chat_id), reason=$4, updated_at=now()
        WHERE id=$1
        RETURNING *
        """,
        measurement_id,
        new_status,
        manager_chat_id,
        reason,
    )
    logger.info("measurement_status_changed", extra={"id": measurement_id, "from": current_status, "to": new_status})
    return dict(row)


async def auto_confirm_due_measurements(pool) -> list[dict[str, Any]]:
    """Auto-confirm measurements that stayed scheduled past the manager decision deadline."""
    rows = await pool.fetch(
        """
        UPDATE measurements
        SET status='confirmed',
            reason=COALESCE(NULLIF(reason, ''), 'Автоподтверждение: менеджер не ответил за 15 минут'),
            updated_at=now()
        WHERE status='scheduled'
          AND COALESCE(auto_confirm_at, created_at + interval '15 minutes') <= now()
        RETURNING *
        """
    )
    confirmed = [dict(row) for row in rows]
    if confirmed:
        logger.info("measurements_auto_confirmed", extra={"count": len(confirmed)})
    return confirmed


async def upsert_measurement_slot(
    pool,
    date: str,
    time: str,
    timezone: str,
    manager_chat_id: int | None = None,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    source: str = "manager",
) -> dict[str, Any]:
    """Store a manager-proposed open slot for calendar/audit purposes."""
    slot_start = validate_time(date, time, timezone)
    conflict = await check_conflict(pool, slot_start, duration_minutes)
    if conflict:
        conflict_time = conflict["scheduled_time"].strftime("%H:%M")
        raise ValueError(f"На {conflict_time} уже есть активный замер рядом с этим временем")
    row = await pool.fetchrow(
        """
        INSERT INTO measurement_slots (slot_start, duration_minutes, source, manager_chat_id, status)
        VALUES ($1, $2, $3, $4, 'open')
        ON CONFLICT (slot_start) DO UPDATE
        SET duration_minutes=EXCLUDED.duration_minutes,
            source=EXCLUDED.source,
            manager_chat_id=COALESCE(EXCLUDED.manager_chat_id, measurement_slots.manager_chat_id),
            status='open',
            updated_at=now()
        RETURNING *
        """,
        slot_start,
        duration_minutes,
        source,
        manager_chat_id,
    )
    return dict(row)


def parse_slot_proposal(text: str, timezone: str, now: datetime | None = None) -> tuple[str, str] | None:
    """Parse simple manager messages like 'завтра на 11:00' into (YYYY-MM-DD, HH:MM)."""
    tz = ZoneInfo(timezone)
    base = now.astimezone(tz) if now else datetime.now(tz)
    lowered = (text or "").strip().lower()
    time_matches = list(re.finditer(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\b", lowered))
    if not time_matches:
        return None
    time_match = time_matches[-1]
    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or "00")

    if "послезавтра" in lowered:
        date_value = (base + timedelta(days=2)).date()
    elif "завтра" in lowered:
        date_value = (base + timedelta(days=1)).date()
    elif "сегодня" in lowered:
        date_value = base.date()
    else:
        iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", lowered)
        dot_match = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", lowered)
        if iso_match:
            date_value = datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
        elif dot_match:
            day = int(dot_match.group(1))
            month = int(dot_match.group(2))
            year_raw = dot_match.group(3)
            year = base.year if not year_raw else int(year_raw)
            if year < 100:
                year += 2000
            date_value = datetime(year, month, day, tzinfo=tz).date()
        else:
            return None
    return date_value.strftime("%Y-%m-%d"), f"{hour:02d}:{minute:02d}"


async def get_measurements_for_date(pool, date: str, timezone: str) -> list[dict]:
    """Get all measurements for a specific date (for Mini App calendar view)."""
    tz = ZoneInfo(timezone)
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
    rows = await pool.fetch(
        """
        SELECT m.*, c.name as c_name, c.phone as c_phone
        FROM measurements m
        LEFT JOIN clients c ON c.chat_id = m.client_chat_id
        WHERE m.scheduled_time::date = $1::date
        ORDER BY m.scheduled_time
        """,
        day,
    )
    return [dict(r) for r in rows]

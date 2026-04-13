"""Measurement scheduling service — no external calendar dependency.

All data lives in PostgreSQL. Handles:
- Time validation (business hours, 15-min alignment, not in past)
- Conflict detection (no overlapping active measurements)
- Available slots query (for Gemini prompt context)
- Full status lifecycle: scheduled → confirmed/rejected/cancelled/completed
- Manager and client notifications via Telegram
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.db import postgres
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Business hours
OPENING_HOUR, OPENING_MINUTE = 9, 30
CLOSING_HOUR, CLOSING_MINUTE = 21, 0
DEFAULT_DURATION_MINUTES = 60
MAX_DAYS_AHEAD = 14
SLOT_STEP_MINUTES = 30

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
    """Check if the requested time slot conflicts with an existing active measurement.

    Returns the conflicting measurement dict, or None if slot is free.
    """
    end = start + timedelta(minutes=duration_minutes)
    row = await pool.fetchrow(
        """
        SELECT id, scheduled_time, duration_minutes, client_name, status
        FROM measurements
        WHERE status IN ('scheduled', 'confirmed')
          AND scheduled_time < $2
          AND (scheduled_time + (duration_minutes || ' minutes')::interval) > $1
        LIMIT 1
        """,
        start,
        end,
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
    day_start = datetime.strptime(date, "%Y-%m-%d").replace(
        hour=OPENING_HOUR, minute=OPENING_MINUTE, second=0, tzinfo=tz
    )
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
    busy_ranges = [
        (row["scheduled_time"], row["scheduled_time"] + timedelta(minutes=row["duration_minutes"]))
        for row in rows
    ]

    slots = []
    current = day_start
    while current + timedelta(minutes=duration_minutes) <= day_end:
        if current > now:  # Don't show past slots
            slot_end = current + timedelta(minutes=duration_minutes)
            is_free = all(
                slot_end <= busy_start or current >= busy_end
                for busy_start, busy_end in busy_ranges
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
            (client_chat_id, scheduled_time, duration_minutes, address, client_name, client_phone, notes, status)
        VALUES ($1, $2, $3, $4, $5, $6, '', 'scheduled')
        RETURNING *
        """,
        chat_id,
        start,
        duration_minutes,
        address or "",
        client_name,
        phone,
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

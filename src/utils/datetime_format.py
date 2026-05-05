"""Local-timezone datetime formatting helpers.

Postgres TIMESTAMPTZ values returned by asyncpg arrive as timezone-aware
datetimes in UTC. Most user-facing strings (WhatsApp messages, manager
notifications) need to be in the configured local timezone (settings.timezone,
e.g. Asia/Bishkek). Forgetting `.astimezone(...)` shows clients UTC times that
are several hours off — see Phase 14.1 reschedule bug.
"""

from __future__ import annotations

from datetime import datetime, timezone as _tz_module
from zoneinfo import ZoneInfo

from src.config import settings


def fmt_local(dt: datetime | None, fmt: str = "%d.%m %H:%M") -> str:
    """Format a datetime in the configured local timezone.

    None → "—". Naive datetime is assumed to be UTC. Returns the string
    formatted via strftime in the local zone.
    """
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz_module.utc)
    return dt.astimezone(ZoneInfo(settings.timezone)).strftime(fmt)

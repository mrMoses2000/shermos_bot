"""Google Calendar measurement scheduling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _parse_start(date: str, time: str, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    if start.minute % 15 != 0:
        raise ValueError("Время замера должно быть кратно 15 минутам")
    opening = start.replace(hour=9, minute=30)
    closing = start.replace(hour=21, minute=0)
    if start < opening or start > closing:
        raise ValueError("Замеры доступны с 09:30 до 21:00")
    now = datetime.now(tz)
    if start < now:
        raise ValueError("Нельзя записать замер в прошлом")
    if start > now + timedelta(days=7):
        raise ValueError("Запись доступна максимум на 7 дней вперед")
    return start


def _insert_event_sync(event_body: dict[str, Any], settings) -> dict[str, Any]:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        settings.gcal_credentials_path,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return service.events().insert(calendarId=settings.gcal_calendar_id, body=event_body).execute()


async def create_measurement_event(
    date: str,
    time: str,
    client_name: str,
    phone: str,
    address: str,
    settings,
) -> dict[str, Any]:
    start = _parse_start(date, time, settings.timezone)
    end = start + timedelta(hours=1)
    event_body = {
        "summary": f"Замер Shermos: {client_name}",
        "description": f"Клиент: {client_name}\nТелефон: {phone}\nАдрес: {address}",
        "location": address,
        "start": {"dateTime": start.isoformat(), "timeZone": settings.timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.timezone},
    }

    if not Path(settings.gcal_credentials_path).exists():
        return {
            "event_id": f"local-{int(start.timestamp())}",
            "html_link": "",
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    loop = asyncio.get_running_loop()
    event = await loop.run_in_executor(None, _insert_event_sync, event_body, settings)
    return {
        "event_id": event.get("id", ""),
        "html_link": event.get("htmlLink", ""),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }

"""Tests for worker background loops.

These verify the wrapper-level behavior of the long-running asyncio loops
(_maintenance_loop, _measurement_auto_confirm_loop, _measurement_reminder_loop)
rather than the individual operations they invoke (those are covered by
test_measurement_service.py / test_postgres_helpers.py).

Specifically we want to know that each loop:

  1. Calls its underlying operation at least once per tick.
  2. Survives a transient error from the operation (logs + continues).
  3. Re-raises asyncio.CancelledError when the task is cancelled — so
     graceful shutdown actually drains them, instead of hanging on a
     swallowed cancel.
"""
from __future__ import annotations

import asyncio

import pytest

from src.queue import worker


# ─── _maintenance_loop ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_maintenance_loop_calls_both_operations(monkeypatch):
    closed_calls = 0
    abandoned_calls = 0

    async def fake_close(_pool, *, grace_hours: int = 24):
        nonlocal closed_calls
        closed_calls += 1
        return 0  # nothing to close, but loop must still keep running

    async def fake_abandon(_pool, *, max_age_hours: int = 24):
        nonlocal abandoned_calls
        abandoned_calls += 1
        return 0

    # auto_close_past_measurements is imported lazily inside the loop body.
    import src.engine.measurement_service as ms
    monkeypatch.setattr(ms, "auto_close_past_measurements", fake_close)
    monkeypatch.setattr(worker.postgres, "abandon_stale_order_drafts", fake_abandon)

    task = asyncio.create_task(worker._maintenance_loop(object(), interval_seconds=0.05))
    await asyncio.sleep(0.13)  # 2-3 ticks
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert closed_calls >= 2, f"Expected ≥2 ticks of auto_close, got {closed_calls}"
    assert abandoned_calls >= 2, f"Expected ≥2 ticks of abandon, got {abandoned_calls}"


@pytest.mark.asyncio
async def test_maintenance_loop_survives_transient_error(monkeypatch):
    """A failing operation must not kill the loop — it should log and retry."""
    call_log = []

    async def flaky_close(_pool, *, grace_hours: int = 24):
        call_log.append("close")
        if len(call_log) == 1:
            raise RuntimeError("transient db blip")
        return 0

    async def ok_abandon(_pool, *, max_age_hours: int = 24):
        call_log.append("abandon")
        return 0

    import src.engine.measurement_service as ms
    monkeypatch.setattr(ms, "auto_close_past_measurements", flaky_close)
    monkeypatch.setattr(worker.postgres, "abandon_stale_order_drafts", ok_abandon)

    task = asyncio.create_task(worker._maintenance_loop(object(), interval_seconds=0.05))
    await asyncio.sleep(0.18)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # First close raised → abandon would have been skipped on tick 1 (we exit
    # the try block early). But subsequent ticks must include both ops.
    assert call_log.count("close") >= 2
    assert call_log.count("abandon") >= 1, "Loop should resume after the transient error"


# ─── _measurement_auto_confirm_loop ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_confirm_loop_propagates_cancel(monkeypatch):
    """Cancel must propagate so graceful shutdown actually finishes."""
    async def fake_auto_confirm(_pool):
        await asyncio.sleep(0)  # yield once
        return []

    async def fake_notify(_pool, _sender, _measurements):
        return None

    import src.engine.measurement_service as ms
    monkeypatch.setattr(ms, "auto_confirm_due_measurements", fake_auto_confirm)
    monkeypatch.setattr(worker, "_notify_auto_confirmed_measurements", fake_notify)

    task = asyncio.create_task(
        worker._measurement_auto_confirm_loop(object(), object(), interval_seconds=0.05)
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_auto_confirm_loop_survives_db_error(monkeypatch):
    """A DB error inside the loop must be logged and not stop the loop."""
    calls = 0

    async def flaky(_pool):
        nonlocal calls
        calls += 1
        raise RuntimeError("db down")

    import src.engine.measurement_service as ms
    monkeypatch.setattr(ms, "auto_confirm_due_measurements", flaky)

    task = asyncio.create_task(
        worker._measurement_auto_confirm_loop(object(), object(), interval_seconds=0.05)
    )
    await asyncio.sleep(0.18)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls >= 2, f"Loop must keep retrying after errors; got {calls} call(s)"


# ─── _measurement_reminder_loop ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reminder_loop_processes_due_measurements(monkeypatch):
    """Reminder loop must consume rows returned by get_due_reminders and
    queue outbound events for both client and managers."""
    from datetime import datetime, timezone

    due_pool = [
        [{
            "id": 42,
            "client_chat_id": 77085766841,
            "client_name": "Тест",
            "client_phone": "+7700",
            "address": "ул. Тестовая, 1",
            "scheduled_time": datetime.now(timezone.utc),
        }],
        [],  # second tick — nothing due
    ]
    inserted = []
    revived = []
    marked = []

    async def fake_get_due(_pool, **_kwargs):
        return due_pool.pop(0) if due_pool else []

    async def fake_revive(_pool, key: str):
        revived.append(key)
        return 0

    async def fake_insert(_pool, **kwargs):
        inserted.append(kwargs)
        return len(inserted)

    async def fake_mark_reminder(_pool, mid: int):
        marked.append(mid)

    import src.engine.measurement_service as ms
    monkeypatch.setattr(ms, "get_due_reminders", fake_get_due)
    monkeypatch.setattr(ms, "mark_reminder_sent", fake_mark_reminder)
    monkeypatch.setattr(worker.postgres, "revive_failed_outbound_by_key", fake_revive)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", fake_insert)
    # The loop reads settings.manager_whatsapp_numbers_list (a derived
    # property). Set the underlying string field so the property returns a
    # single deterministic phone for the test.
    monkeypatch.setattr(worker.settings, "manager_whatsapp_numbers", "77001112233")

    task = asyncio.create_task(
        worker._measurement_reminder_loop(object(), interval_seconds=0.05)
    )
    await asyncio.sleep(0.13)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # One client outbound + one manager outbound = 2 rows queued for the
    # single due measurement on the first tick.
    assert len(inserted) == 2, f"Expected 2 outbounds (client+manager), got {len(inserted)}"
    bot_types = sorted(o.get("bot_type") for o in inserted)
    assert bot_types == ["client", "manager"]

    # revive must run before each insert (so a previously-failed outbound
    # row with the same idempotency_key gets cleared first).
    assert "reminder:42" in revived
    assert "reminder:42:77001112233" in revived

    assert marked == [42], "Reminder must be marked sent (telemetry)"

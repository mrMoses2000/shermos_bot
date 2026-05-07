"""Tests for the render-in-progress watchdog in src.queue.worker.

Verifies that:
  - watchdog is NOT scheduled when LLM did not request render_partition
    (avoids extra noise on simple chat replies);
  - watchdog IS scheduled when render_partition is requested, and the
    interim message is sent if apply_actions is slow;
  - watchdog is cancelled when apply_actions completes quickly, so the
    user does not get the "still working" message after the render is
    already delivered;
  - watchdog respects render_progress_notify_after_seconds=0 (disabled).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models import ActionsJson
from src.queue import worker


def _settings(notify_after: int = 0) -> SimpleNamespace:
    return SimpleNamespace(render_progress_notify_after_seconds=notify_after)


@pytest.mark.asyncio
async def test_watchdog_not_started_without_render_action():
    parsed = ActionsJson(reply_text="Привет", actions=None)
    sender = AsyncMock()
    task = worker._start_render_progress_watchdog(
        parsed, pg_pool=object(), sender=sender, chat_id=42, settings=_settings(1)
    )
    assert task is None


@pytest.mark.asyncio
async def test_watchdog_disabled_when_threshold_zero():
    parsed = ActionsJson(reply_text="ok", actions={"render_partition": {"shape": "Прямая"}})
    task = worker._start_render_progress_watchdog(
        parsed, pg_pool=object(), sender=AsyncMock(), chat_id=42, settings=_settings(0)
    )
    assert task is None


@pytest.mark.asyncio
async def test_watchdog_sends_interim_message_after_delay(monkeypatch):
    """When apply_actions takes longer than the threshold, watchdog sends one message."""
    sent: list[str] = []

    async def fake_send_and_record(_pool, _sender, _kind, chat_id, text, **kwargs):
        sent.append(text)
        return 1

    monkeypatch.setattr(worker, "send_and_record", fake_send_and_record)
    parsed = ActionsJson(
        reply_text="секунду",
        actions={"render_partition": {"shape": "П-образная"}},
    )

    # Use a near-zero threshold so the test stays fast.
    task = worker._start_render_progress_watchdog(
        parsed, pg_pool=object(), sender=AsyncMock(), chat_id=99,
        settings=SimpleNamespace(render_progress_notify_after_seconds=0.05),
    )
    assert task is not None
    await asyncio.sleep(0.15)  # let the sleep+send fire
    assert sent, "watchdog must have sent an interim message"
    assert "3D" in sent[0]
    # And the task must finish on its own
    await task


@pytest.mark.asyncio
async def test_watchdog_is_cancellable_before_firing(monkeypatch):
    """Caller cancels the watchdog as soon as apply_actions returns; the
    interim message must not be sent."""
    sent: list[str] = []

    async def fake_send_and_record(_pool, _sender, _kind, chat_id, text, **kwargs):
        sent.append(text)
        return 1

    monkeypatch.setattr(worker, "send_and_record", fake_send_and_record)
    parsed = ActionsJson(
        reply_text="ok",
        actions={"render_partition": {"shape": "Прямая"}},
    )

    task = worker._start_render_progress_watchdog(
        parsed, pg_pool=object(), sender=AsyncMock(), chat_id=99,
        settings=SimpleNamespace(render_progress_notify_after_seconds=5),
    )
    assert task is not None
    # Simulate a fast apply_actions: cancel immediately
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sent == [], "no interim message must be sent if cancelled in time"

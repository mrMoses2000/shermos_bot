"""Tests for sd_notify watchdog module (step 5.3).

All tests must pass on macOS where systemd is not installed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


def test_import_succeeds_without_systemd():
    """src.utils.watchdog imports cleanly even without python-systemd."""
    import src.utils.watchdog as wd

    assert hasattr(wd, "notify_ready")
    assert hasattr(wd, "notify_watchdog")
    assert hasattr(wd, "notify_stopping")
    assert hasattr(wd, "run_watchdog_loop")


def test_notify_ready_noop_without_systemd():
    """notify_ready() does not raise when _HAS_SYSTEMD is False."""
    import src.utils.watchdog as wd

    with patch.object(wd, "_HAS_SYSTEMD", False):
        wd.notify_ready()  # must not raise


def test_notify_watchdog_noop_without_systemd():
    """notify_watchdog() does not raise when _HAS_SYSTEMD is False."""
    import src.utils.watchdog as wd

    with patch.object(wd, "_HAS_SYSTEMD", False):
        wd.notify_watchdog()  # must not raise


def test_notify_stopping_noop_without_systemd():
    """notify_stopping() does not raise when _HAS_SYSTEMD is False."""
    import src.utils.watchdog as wd

    with patch.object(wd, "_HAS_SYSTEMD", False):
        wd.notify_stopping()  # must not raise


def test_notify_ready_calls_sd_when_systemd_present():
    """notify_ready() calls sd_daemon.notify('READY=1') when _HAS_SYSTEMD is True."""
    import src.utils.watchdog as wd

    mock_sd = MagicMock()
    with patch.object(wd, "_HAS_SYSTEMD", True), patch.object(wd, "_sd_daemon", mock_sd):
        wd.notify_ready()
        mock_sd.notify.assert_called_once_with("READY=1")


def test_notify_watchdog_calls_sd_when_systemd_present():
    """notify_watchdog() calls sd_daemon.notify('WATCHDOG=1') when _HAS_SYSTEMD is True."""
    import src.utils.watchdog as wd

    mock_sd = MagicMock()
    with patch.object(wd, "_HAS_SYSTEMD", True), patch.object(wd, "_sd_daemon", mock_sd):
        wd.notify_watchdog()
        mock_sd.notify.assert_called_once_with("WATCHDOG=1")


def test_notify_stopping_calls_sd_when_systemd_present():
    """notify_stopping() calls sd_daemon.notify('STOPPING=1') when _HAS_SYSTEMD is True."""
    import src.utils.watchdog as wd

    mock_sd = MagicMock()
    with patch.object(wd, "_HAS_SYSTEMD", True), patch.object(wd, "_sd_daemon", mock_sd):
        wd.notify_stopping()
        mock_sd.notify.assert_called_once_with("STOPPING=1")


async def test_watchdog_loop_calls_notify_watchdog():
    """run_watchdog_loop ticks once and calls notify_watchdog before cancellation."""
    import src.utils.watchdog as wd

    call_count = 0

    def _fake_notify_watchdog():
        nonlocal call_count
        call_count += 1

    with patch.object(wd, "notify_watchdog", side_effect=_fake_notify_watchdog):
        # Use a very short interval so the loop ticks immediately
        task = asyncio.create_task(wd.run_watchdog_loop(interval_seconds=0))
        # Yield control so the loop executes at least once
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert call_count >= 1, f"Expected notify_watchdog called ≥1 time, got {call_count}"

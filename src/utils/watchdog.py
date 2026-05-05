"""Optional sd_notify integration. No-op when systemd is not present.

On Linux with systemd and Type=notify + WatchdogSec=60 in the unit file,
these functions signal readiness, liveness, and graceful shutdown to the
service manager.  On macOS (dev environment) or any system without
python-systemd installed, all calls silently become no-ops.
"""

from __future__ import annotations

import asyncio

try:
    import systemd.daemon as _sd_daemon  # python-systemd (Linux / production)

    _HAS_SYSTEMD = True
except ImportError:
    _sd_daemon = None  # type: ignore[assignment]
    _HAS_SYSTEMD = False


def notify_ready() -> None:
    """Send READY=1 to systemd (service startup complete)."""
    if _HAS_SYSTEMD:
        _sd_daemon.notify("READY=1")


def notify_watchdog() -> None:
    """Send WATCHDOG=1 to systemd (process is alive)."""
    if _HAS_SYSTEMD:
        _sd_daemon.notify("WATCHDOG=1")


def notify_stopping() -> None:
    """Send STOPPING=1 to systemd (graceful shutdown initiated)."""
    if _HAS_SYSTEMD:
        _sd_daemon.notify("STOPPING=1")


async def run_watchdog_loop(interval_seconds: int = 30) -> None:
    """Periodically call notify_watchdog() until cancelled.

    Run this as a background asyncio task alongside the main worker loop.
    The interval should be less than half of WatchdogSec (e.g. 30 s when
    WatchdogSec=60) so that a single missed tick does not trigger a restart.
    """
    while True:
        notify_watchdog()
        await asyncio.sleep(interval_seconds)

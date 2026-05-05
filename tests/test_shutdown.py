"""Tests for graceful SIGTERM/SIGINT shutdown of run_worker and run_webhook."""

from __future__ import annotations

import asyncio
import signal

import pytest


@pytest.mark.asyncio
async def test_worker_sigterm_sets_stop_event_and_cancels_main_task(monkeypatch):
    """Sending SIGTERM to the event loop triggers graceful shutdown of run_worker._main."""
    import run_worker

    async def fake_run_worker():
        await asyncio.sleep(60)

    monkeypatch.setattr(run_worker, "run_worker", fake_run_worker)

    # Run _main in a background task; after a brief delay send SIGTERM via os.kill.
    import os

    main_task = asyncio.create_task(run_worker._main())
    await asyncio.sleep(0.05)  # let signal handlers register
    os.kill(os.getpid(), signal.SIGTERM)
    # _main should complete cleanly within a short timeout
    await asyncio.wait_for(main_task, timeout=3.0)
    # If we reach here without TimeoutError the shutdown was clean
    assert main_task.done()
    assert not main_task.cancelled()


@pytest.mark.asyncio
async def test_worker_sigint_shuts_down_cleanly(monkeypatch):
    """SIGINT (Ctrl-C equivalent) also triggers graceful shutdown."""
    import run_worker

    async def fake_run_worker():
        await asyncio.sleep(60)

    monkeypatch.setattr(run_worker, "run_worker", fake_run_worker)

    import os

    main_task = asyncio.create_task(run_worker._main())
    await asyncio.sleep(0.05)
    os.kill(os.getpid(), signal.SIGINT)
    await asyncio.wait_for(main_task, timeout=3.0)
    assert main_task.done()
    assert not main_task.cancelled()


@pytest.mark.asyncio
async def test_worker_shutdown_logs_are_emitted(monkeypatch):
    """worker_shutdown_initiated and worker_shutdown_complete are logged.

    The custom setup_logger sets propagate=False so caplog won't capture records
    from these loggers. Instead we monkeypatch logger.info directly.
    """
    import run_worker

    logged: list[str] = []

    def fake_info(msg, *args, **kwargs):
        logged.append(msg)

    monkeypatch.setattr(run_worker.logger, "info", fake_info)

    async def fake_run_worker():
        await asyncio.sleep(60)

    monkeypatch.setattr(run_worker, "run_worker", fake_run_worker)

    import os

    main_task = asyncio.create_task(run_worker._main())
    await asyncio.sleep(0.05)
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(main_task, timeout=3.0)

    assert "worker_shutdown_initiated" in logged, logged
    assert "worker_shutdown_complete" in logged, logged


@pytest.mark.asyncio
async def test_worker_main_task_completes_naturally(monkeypatch):
    """If run_worker exits on its own (no signal), _main returns cleanly too."""
    import run_worker

    async def fake_run_worker():
        # Exits immediately to simulate a normal stop
        return

    monkeypatch.setattr(run_worker, "run_worker", fake_run_worker)

    await asyncio.wait_for(run_worker._main(), timeout=3.0)



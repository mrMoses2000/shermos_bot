"""Tests for src.llm.executor logging behavior.

Specifically the near-timeout WARNING upgrade — when an LLM call burns
≥70% of the configured timeout, we want to see a `WARNING llm_call_finished`
in journals so degradation trends show up before clients actually hit the
timeout (the failure mode that lost a real client message on 2026-05-10).
"""
from __future__ import annotations

import logging

import pytest

from src.llm import executor


@pytest.fixture(autouse=True)
def _propagate_executor_logger():
    """src.utils.logger.setup_logger sets propagate=False so structured logs
    don't double-print. caplog hooks the root logger, so without propagation
    these tests would never see the records."""
    log = logging.getLogger("src.llm.executor")
    prev = log.propagate
    log.propagate = True
    try:
        yield
    finally:
        log.propagate = prev


class _FakeProcess:
    """Minimal stand-in for asyncio.subprocess.Process that controls the
    duration `communicate()` simulates by yielding control once."""

    def __init__(self, stdout: bytes = b"ok", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.pid = 12345

    async def communicate(self, input=None):  # noqa: ARG002
        return self._stdout, self._stderr

    async def wait(self):
        return self.returncode


async def _fake_subprocess_exec(*_args, **_kwargs):
    return _FakeProcess()


@pytest.mark.asyncio
async def test_llm_call_logs_at_info_for_fast_call(monkeypatch, caplog):
    """A short call (well under the timeout) must log at INFO, not WARNING."""
    monkeypatch.setattr(executor.settings, "llm_timeout_seconds", 100)
    monkeypatch.setattr(executor.asyncio, "create_subprocess_exec", _fake_subprocess_exec)

    # perf_counter is called twice: once before subprocess starts, once after
    # communicate() returns. Returning [0.0, 5.0] yields a duration of 5s —
    # only 5% of the 100s ceiling.
    # perf_counter is called 4× per call (wait_start, waited, exec_start,
    # duration). We control the *spread* so duration ≈ 5s.
    times = iter([0.0, 0.0, 0.0, 5.0])
    monkeypatch.setattr(executor.time, "perf_counter", lambda: next(times))

    with caplog.at_level(logging.INFO, logger="src.llm.executor"):
        await executor.call_llm("hi")

    finished = [r for r in caplog.records if r.message == "llm_call_finished"]
    assert finished, "Expected an llm_call_finished record"
    assert finished[-1].levelno == logging.INFO


@pytest.mark.asyncio
async def test_llm_call_logs_at_warning_when_near_timeout(monkeypatch, caplog):
    """Burning 80% of the budget must surface as WARNING — early-warning
    signal for ops without waiting for the actual timeout to fire."""
    monkeypatch.setattr(executor.settings, "llm_timeout_seconds", 100)
    monkeypatch.setattr(executor.asyncio, "create_subprocess_exec", _fake_subprocess_exec)

    times = iter([0.0, 0.0, 0.0, 80.0])  # 80s exec on a 100s budget — 80% (over the 70% threshold)
    monkeypatch.setattr(executor.time, "perf_counter", lambda: next(times))

    with caplog.at_level(logging.INFO, logger="src.llm.executor"):
        await executor.call_llm("hi")

    finished = [r for r in caplog.records if r.message == "llm_call_finished"]
    assert finished, "Expected an llm_call_finished record"
    assert finished[-1].levelno == logging.WARNING
    # Extra fields must include the timeout context so journal queries can
    # filter on the configured ceiling.
    assert getattr(finished[-1], "timeout_s", None) == 100
    assert getattr(finished[-1], "t_exec_llm", None) == 80.0


@pytest.mark.asyncio
async def test_llm_call_logs_warning_at_exact_70pct_boundary(monkeypatch, caplog):
    """Exactly 70% must already be WARNING — the threshold is inclusive
    (>= 0.7) so a 70.0s on a 100s budget trips it."""
    monkeypatch.setattr(executor.settings, "llm_timeout_seconds", 100)
    monkeypatch.setattr(executor.asyncio, "create_subprocess_exec", _fake_subprocess_exec)

    times = iter([0.0, 0.0, 0.0, 70.0])  # exactly 70s on 100s — boundary case
    monkeypatch.setattr(executor.time, "perf_counter", lambda: next(times))

    with caplog.at_level(logging.INFO, logger="src.llm.executor"):
        await executor.call_llm("hi")

    finished = [r for r in caplog.records if r.message == "llm_call_finished"]
    assert finished[-1].levelno == logging.WARNING

"""Tests for the render-engine timeout/observability changes.

We do not spawn the real renderer — only verify that:
  - render_partition honors `settings.render_timeout_seconds`,
  - on timeout, the SIGKILL'ed subprocess raises a labeled TimeoutError
    that includes both the configured budget and the elapsed time,
  - a successful run logs render_started/render_finished.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.engine import render_engine


def _fake_settings(tmp_path, *, timeout: int = 300) -> SimpleNamespace:
    return SimpleNamespace(
        renders_dir=str(tmp_path),
        render_timeout_seconds=timeout,
    )


def _stub_render_helpers(monkeypatch, *, png_files: list[str] | None = None):
    """Bypass _render_params and _collect_render_paths so we can focus on
    the subprocess-management code paths."""
    monkeypatch.setattr(render_engine, "_render_params", lambda params: {"shape": "П"})
    from src.render import validators as v

    monkeypatch.setattr(v, "validate_partition_params", lambda _p: (True, []))
    files = png_files if png_files is not None else ["a.png", "b.png", "c.png", "d.png"]
    monkeypatch.setattr(
        render_engine,
        "_collect_render_paths",
        lambda _out: {f"{i*90}deg": p for i, p in enumerate(files)},
    )


class _FakeStream:
    def __init__(self, payload: bytes):
        self._payload = payload

    async def read(self, _n=-1):
        return self._payload


class _FakeProc:
    """Replacement for asyncio.subprocess.Process for two scenarios:
    fast-success and timeout-then-killed."""

    def __init__(self, *, succeed: bool, returncode: int = 0, stderr: bytes = b""):
        self.pid = 12345
        self.returncode = returncode if succeed else None
        self._succeed = succeed
        self._stderr_payload = stderr
        self.stderr = _FakeStream(stderr)

    async def communicate(self):
        if not self._succeed:
            raise asyncio.TimeoutError
        return (b"", self._stderr_payload)

    async def wait(self):
        return self.returncode or 0


@pytest.mark.asyncio
async def test_render_uses_settings_timeout(tmp_path, monkeypatch, caplog):
    """settings.render_timeout_seconds must be the wait_for budget."""
    _stub_render_helpers(monkeypatch)

    captured = {}

    async def fake_wait_for(coro, timeout):
        captured["timeout"] = timeout
        return await coro

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return _FakeProc(succeed=True)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    caplog.set_level(logging.INFO, logger="src.engine.render_engine")
    settings = _fake_settings(tmp_path, timeout=275)

    result = await render_engine.render_partition(
        SimpleNamespace(model_dump=lambda exclude_none=False: {}),
        "req-1",
        settings,
    )

    assert captured["timeout"] == 275, "render_partition must pass settings.render_timeout_seconds to wait_for"
    assert result["render_paths"]
    # Logged structured events on the happy path
    msgs = [r.getMessage() for r in caplog.records]
    assert "render_started" in msgs
    assert "render_finished" in msgs


@pytest.mark.asyncio
async def test_render_timeout_includes_elapsed_and_budget(tmp_path, monkeypatch, caplog):
    """On timeout we must:
      - SIGKILL the process group,
      - wait() the proc,
      - log render_timeout with stderr_tail and elapsed,
      - raise TimeoutError mentioning the configured budget.
    """
    _stub_render_helpers(monkeypatch)

    # wait_for is called twice in the timeout path: first for communicate()
    # (that we want to time out) and then a second short read of stderr
    # (that we want to actually run). Patch only the first call.
    real_wait_for = asyncio.wait_for
    calls = {"n": 0}

    async def fake_wait_for(coro, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            # close the unawaited coroutine to avoid resource warnings
            coro.close()
            raise asyncio.TimeoutError
        return await real_wait_for(coro, timeout)

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    fake_proc = _FakeProc(succeed=False, stderr=b"GL context init: very slow on this hw")

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    killed = {"called": False}

    def fake_killpg(_pgid, _sig):
        killed["called"] = True

    monkeypatch.setattr(render_engine.os, "killpg", fake_killpg)
    monkeypatch.setattr(render_engine.os, "getpgid", lambda _pid: 99)

    caplog.set_level(logging.ERROR, logger="src.engine.render_engine")
    settings = _fake_settings(tmp_path, timeout=42)

    with pytest.raises(TimeoutError) as exc_info:
        await render_engine.render_partition(
            SimpleNamespace(model_dump=lambda exclude_none=False: {}),
            "req-2",
            settings,
        )
    msg = str(exc_info.value)
    assert "42s" in msg, f"timeout error must include configured budget, got: {msg}"
    assert "elapsed" in msg
    assert killed["called"], "render_partition must SIGKILL the process group on timeout"

    # Structured timeout log with stderr tail
    timeout_records = [r for r in caplog.records if r.getMessage() == "render_timeout"]
    assert timeout_records, "render_timeout event must be logged"
    rec = timeout_records[-1]
    assert getattr(rec, "timeout", None) == 42
    assert "very slow" in getattr(rec, "stderr_tail", "")


@pytest.mark.asyncio
async def test_render_falls_back_to_default_timeout_when_unset(tmp_path, monkeypatch):
    """If settings does not have render_timeout_seconds, use the module default."""
    _stub_render_helpers(monkeypatch)

    captured = {}

    async def fake_wait_for(coro, timeout):
        captured["timeout"] = timeout
        return await coro

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return _FakeProc(succeed=True)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    settings_without = SimpleNamespace(renders_dir=str(tmp_path))
    await render_engine.render_partition(
        SimpleNamespace(model_dump=lambda exclude_none=False: {}),
        "req-3",
        settings_without,
    )
    assert captured["timeout"] == render_engine._DEFAULT_RENDER_TIMEOUT

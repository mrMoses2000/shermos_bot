"""Tests for src.llm.health_check — 2.5 remediation."""

from __future__ import annotations

import asyncio

import pytest

import src.llm.health_check as hc_module
from src.llm.health_check import _one_tick, is_gemini_healthy


@pytest.fixture(autouse=True)
def reset_healthy_state():
    """Reset global healthy state before each test."""
    hc_module._gemini_healthy = True
    yield
    hc_module._gemini_healthy = True


@pytest.mark.asyncio
async def test_one_tick_healthy_on_ok_response(monkeypatch):
    """2.5 — call_llm returning 'ok' sets is_gemini_healthy() to True."""

    async def fake_call_llm(_prompt):
        return '{"reply_text":"ok","actions":null}'

    monkeypatch.setattr(hc_module, "call_llm", fake_call_llm)
    hc_module._gemini_healthy = False  # start unhealthy so recovery log fires

    await _one_tick()

    assert is_gemini_healthy() is True


@pytest.mark.asyncio
async def test_one_tick_unhealthy_on_garbage_output(monkeypatch):
    """2.5 — call_llm returning random garbage sets is_gemini_healthy() to False and logs warning."""
    warning_calls = []

    async def fake_call_llm(_prompt):
        return "random garbage"

    monkeypatch.setattr(hc_module, "call_llm", fake_call_llm)
    monkeypatch.setattr(hc_module.logger, "warning", lambda msg, **kw: warning_calls.append(msg))

    await _one_tick()

    assert is_gemini_healthy() is False
    assert any("gemini_health_unexpected_output" in c for c in warning_calls)


@pytest.mark.asyncio
async def test_one_tick_unhealthy_on_timeout(monkeypatch):
    """2.5 — call_llm raising TimeoutError sets is_gemini_healthy() to False and logs critical."""
    critical_calls = []

    async def fake_call_llm(_prompt):
        raise TimeoutError("LLM timed out")

    monkeypatch.setattr(hc_module, "call_llm", fake_call_llm)
    monkeypatch.setattr(hc_module.logger, "critical", lambda msg, **kw: critical_calls.append(msg))

    await _one_tick()

    assert is_gemini_healthy() is False
    assert any("gemini_health_check_failed" in c for c in critical_calls)


@pytest.mark.asyncio
async def test_one_tick_recovery_after_failure(monkeypatch):
    """2.5 — call_llm recovering after an exception logs 'gemini_health_recovered'."""
    calls = {"count": 0}
    info_calls = []

    async def fake_call_llm(_prompt):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("first call fails")
        return '{"reply_text":"ok"}'

    monkeypatch.setattr(hc_module, "call_llm", fake_call_llm)
    monkeypatch.setattr(hc_module.logger, "critical", lambda msg, **kw: None)
    monkeypatch.setattr(hc_module.logger, "info", lambda msg, **kw: info_calls.append(msg))

    # First tick — should fail
    await _one_tick()
    assert is_gemini_healthy() is False

    # Second tick — should recover
    await _one_tick()
    assert is_gemini_healthy() is True
    assert any("gemini_health_recovered" in c for c in info_calls)

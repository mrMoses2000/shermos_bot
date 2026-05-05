"""Tests for syslog-priority formatter in logger.py (step 5.2)."""

from __future__ import annotations

import io
import logging
import os


def _fresh_logger(name: str, monkeypatch, log_syslog_prio: str = "1", log_format: str = "json") -> tuple[logging.Logger, io.StringIO]:
    """Return a freshly configured logger + StringIO stream it writes to."""
    # Unregister any existing handlers so setup_logger re-initialises
    existing = logging.getLogger(name)
    existing.handlers.clear()

    monkeypatch.setenv("LOG_SYSLOG_PRIORITY", log_syslog_prio)
    monkeypatch.setenv("LOG_FORMAT", log_format)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    # Re-import to pick up env changes (the function reads env at call time)
    from src.utils.logger import setup_logger

    stream = io.StringIO()
    logger = setup_logger(name)
    # Replace the handler's stream with our capture buffer
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream
    return logger, stream


def test_warning_gets_syslog_prefix(monkeypatch):
    """WARNING log line starts with <4> when LOG_SYSLOG_PRIORITY=1."""
    logger, stream = _fresh_logger("test.warn", monkeypatch, log_syslog_prio="1")
    logger.warning("hello warning")
    out = stream.getvalue()
    assert out.startswith("<4>"), f"Expected <4> prefix, got: {out!r}"


def test_error_gets_syslog_prefix(monkeypatch):
    """ERROR log line starts with <3> when LOG_SYSLOG_PRIORITY=1."""
    logger, stream = _fresh_logger("test.error", monkeypatch, log_syslog_prio="1")
    logger.error("hello error")
    out = stream.getvalue()
    assert out.startswith("<3>"), f"Expected <3> prefix, got: {out!r}"


def test_critical_gets_syslog_prefix(monkeypatch):
    """CRITICAL log line starts with <2> when LOG_SYSLOG_PRIORITY=1."""
    logger, stream = _fresh_logger("test.crit", monkeypatch, log_syslog_prio="1")
    logger.critical("hello critical")
    out = stream.getvalue()
    assert out.startswith("<2>"), f"Expected <2> prefix, got: {out!r}"


def test_info_gets_syslog_prefix(monkeypatch):
    """INFO log line starts with <6> when LOG_SYSLOG_PRIORITY=1."""
    logger, stream = _fresh_logger("test.info", monkeypatch, log_syslog_prio="1")
    logger.info("hello info")
    out = stream.getvalue()
    assert out.startswith("<6>"), f"Expected <6> prefix, got: {out!r}"


def test_no_prefix_when_disabled(monkeypatch):
    """When LOG_SYSLOG_PRIORITY=0, lines do NOT start with <N>."""
    logger, stream = _fresh_logger("test.noprefix", monkeypatch, log_syslog_prio="0")
    logger.warning("plain warning")
    out = stream.getvalue()
    assert not out.startswith("<"), f"Expected no syslog prefix, got: {out!r}"


def test_json_line_preserved_after_prefix(monkeypatch):
    """The JSON payload is still valid JSON after stripping the prefix."""
    import json

    logger, stream = _fresh_logger("test.json", monkeypatch, log_syslog_prio="1")
    logger.error("structured error")
    out = stream.getvalue().strip()
    # Strip the syslog prefix (<3>)
    assert out.startswith("<3>")
    json_part = out[3:]
    parsed = json.loads(json_part)
    assert parsed.get("level") == "ERROR"
    assert parsed.get("message") == "structured error"

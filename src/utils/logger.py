"""Small structured logging helper used by app code and legacy render modules."""

from __future__ import annotations

import functools
import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# RFC 5424 / sd-journal priority prefixes that systemd reads from stdout.
# systemd strips them before storing; they never appear in journalctl output.
# On a TTY the prefix is visible but harmless (small visual blemish accepted
# for the sake of simplicity — no TTY detection needed).
# Toggle via LOG_SYSLOG_PRIORITY=0 (default: 1 = enabled).
_SYSLOG_PRIORITY: dict[str, str] = {
    "DEBUG": "<7>",
    "INFO": "<6>",
    "WARNING": "<4>",
    "ERROR": "<3>",
    "CRITICAL": "<2>",
}


class SystemdPriorityFormatter(logging.Formatter):
    """Prepends a syslog-priority prefix (<N>) to every formatted log line.

    systemd parses these prefixes from stdout/stderr (sd_journal_stream_fd)
    and maps them to the matching journal priority, making
    ``journalctl -u shermos-worker -p err`` return only ERROR/CRITICAL entries.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        prefix = _SYSLOG_PRIORITY.get(record.levelname, "<6>")
        return prefix + base


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in payload or key in _RESERVED_LOG_RECORD_KEYS:
                continue
            try:
                json.dumps(value)
            except TypeError:
                payload[key] = repr(value)
            else:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


_RESERVED_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def _make_formatter() -> logging.Formatter:
    """Build the active formatter based on env vars.

    LOG_FORMAT=json (default) → JSON lines.
    LOG_SYSLOG_PRIORITY=1 (default) → wrap with SystemdPriorityFormatter so
    that each line starts with the SD_* priority prefix (<N>).  systemd strips
    the prefix before storing; terminals display it verbatim (accepted trade-off
    for simplicity — no TTY detection required).
    """
    use_json = os.getenv("LOG_FORMAT", "json").lower() == "json"
    use_syslog_prio = os.getenv("LOG_SYSLOG_PRIORITY", "1") not in ("0", "false", "no")

    if use_json:
        base_fmt: logging.Formatter = JsonFormatter()
    else:
        base_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if use_syslog_prio:
        # Wrap: SystemdPriorityFormatter delegates format() to base_fmt via
        # its own super().format() — but since we want the base to be the
        # JSON formatter (not the default Formatter), we sub-class dynamically.
        class _Wrapped(SystemdPriorityFormatter):
            _base = base_fmt

            def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
                base = self._base.format(record)
                prefix = _SYSLOG_PRIORITY.get(record.levelname, "<6>")
                return prefix + base

        return _Wrapped()

    return base_fmt


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    handler = logging.StreamHandler()
    handler.setFormatter(_make_formatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_function_call(func: F) -> F:
    logger = setup_logger(func.__module__)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            logger.debug(
                "function_call",
                extra={
                    "function": func.__name__,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )

    return wrapper  # type: ignore[return-value]

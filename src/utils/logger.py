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


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    handler = logging.StreamHandler()
    if os.getenv("LOG_FORMAT", "json").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
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

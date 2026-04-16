"""Helpers for defensive JSON payload normalization."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def decode_nested_json(value: Any) -> Any:
    """Decode values that were accidentally stored as JSON strings."""
    decoded = value
    while isinstance(decoded, str):
        text = decoded.strip()
        if not text:
            return decoded
        try:
            next_value = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return decoded
        if next_value == decoded:
            return decoded
        decoded = next_value
    return decoded


def ensure_json_object(value: Any) -> dict[str, Any]:
    decoded = decode_nested_json(value)
    if isinstance(decoded, Mapping):
        return dict(decoded)
    return {}


def ensure_json_array(value: Any) -> list[Any]:
    decoded = decode_nested_json(value)
    if isinstance(decoded, list):
        return decoded
    return []

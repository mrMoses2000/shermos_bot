"""Validation of user-provided render inputs before expensive rendering."""

from __future__ import annotations

from typing import Any

from src.engine.fsm import get_missing_params
from src.utils.json_tools import ensure_json_object
from src.utils.query_parser import normalize_render_params


def merge_render_params(
    collected_params: dict[str, Any] | None,
    action_params: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = ensure_json_object(collected_params)
    merged.update(ensure_json_object(action_params))
    return merged


def missing_render_params(params: dict[str, Any] | None) -> list[str]:
    raw = ensure_json_object(params)
    normalized = normalize_render_params(raw)
    for required_key in ("shape", "partition_type", "glass_type", "frame_color", "matting"):
        if raw.get(required_key) in (None, ""):
            normalized[required_key] = None
    return get_missing_params(normalized, normalized.get("shape"))

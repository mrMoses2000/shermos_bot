"""Normalization helpers for user-facing LLM/action parameters."""

from __future__ import annotations

from typing import Any

SHAPE_ALIASES = {
    "прямая": "Прямая",
    "прямой": "Прямая",
    "straight": "Прямая",
    "l": "Г-образная",
    "г": "Г-образная",
    "г-образная": "Г-образная",
    "угловая": "Г-образная",
    "u": "П-образная",
    "п": "П-образная",
    "п-образная": "П-образная",
}

HANDLE_POSITION_ALIASES = {
    "left": "Лево",
    "лево": "Лево",
    "слева": "Лево",
    "center": "Центр",
    "центр": "Центр",
    "по центру": "Центр",
    "right": "Право",
    "право": "Право",
    "справа": "Право",
}


def normalize_shape(value: str | None) -> str:
    if not value:
        return "Прямая"
    stripped = value.strip()
    return SHAPE_ALIASES.get(stripped.lower(), stripped)


def normalize_handle_position(value: str | None) -> str:
    if not value:
        return "Право"
    stripped = value.strip()
    return HANDLE_POSITION_ALIASES.get(stripped.lower(), stripped)


def normalize_render_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    normalized["shape"] = normalize_shape(normalized.get("shape"))
    normalized["handle_position"] = normalize_handle_position(normalized.get("handle_position"))
    normalized["glass_type"] = str(normalized.get("glass_type") or "1")
    normalized["frame_color"] = str(normalized.get("frame_color") or "1")
    if normalized.get("width_b") in ("", 0):
        normalized["width_b"] = None
    if normalized.get("width_c") in ("", 0):
        normalized["width_c"] = None
    if normalized.get("door_section") is not None:
        normalized["door_sections"] = [int(normalized["door_section"])]
    return normalized

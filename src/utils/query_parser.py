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

PARTITION_TYPE_ALIASES = {
    "стационарная": "fixed",
    "стационарный": "fixed",
    "fixed": "fixed",
    "раздвижная 2": "sliding_2",
    "раздвижная 2 створки": "sliding_2",
    "2 створки": "sliding_2",
    "sliding_2": "sliding_2",
    "sliding2": "sliding_2",
    "раздвижная 3": "sliding_3",
    "раздвижная 3 створки": "sliding_3",
    "3 створки": "sliding_3",
    "sliding_3": "sliding_3",
    "sliding3": "sliding_3",
    "раздвижная 4": "sliding_4",
    "раздвижная 4 створки": "sliding_4",
    "4 створки": "sliding_4",
    "sliding_4": "sliding_4",
    "sliding4": "sliding_4",
}

MATTING_ALIASES = {
    "нет": "none",
    "без": "none",
    "none": "none",
    "сплошная": "matting_solid",
    "сплошная матировка": "matting_solid",
    "matting_solid": "matting_solid",
    "полосы": "matting_stripes",
    "матовые полосы": "matting_stripes",
    "matting_stripes": "matting_stripes",
    "рисунок": "matting_logo",
    "логотип": "matting_logo",
    "матовый рисунок": "matting_logo",
    "matting_logo": "matting_logo",
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


def normalize_partition_type(value: str | None) -> str:
    if not value:
        return "sliding_2"
    stripped = value.strip()
    return PARTITION_TYPE_ALIASES.get(stripped.lower(), stripped)


def normalize_matting(value: str | None) -> str:
    if not value:
        return "none"
    stripped = value.strip()
    return MATTING_ALIASES.get(stripped.lower(), stripped)


def normalize_render_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    normalized["shape"] = normalize_shape(normalized.get("shape"))
    normalized["handle_position"] = normalize_handle_position(normalized.get("handle_position"))
    normalized["partition_type"] = normalize_partition_type(normalized.get("partition_type"))
    normalized["matting"] = normalize_matting(normalized.get("matting"))
    normalized["glass_type"] = str(normalized.get("glass_type") or "1")
    normalized["frame_color"] = str(normalized.get("frame_color") or "1")
    if normalized.get("width_b") in ("", 0):
        normalized["width_b"] = None
    if normalized.get("width_c") in ("", 0):
        normalized["width_c"] = None
    if normalized.get("door_section") is not None:
        normalized["door_sections"] = [int(normalized["door_section"])]
    return normalized

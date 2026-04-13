"""Finite State Machine for parameter collection."""

from __future__ import annotations

from typing import Any

VALID_TRANSITIONS = {
    "idle": {"idle", "collecting", "scheduling"},
    "collecting": {"collecting", "confirming", "idle"},
    "confirming": {"rendering", "collecting", "idle"},
    "rendering": {"idle"},
    "scheduling": {"scheduling", "idle"},
}


def is_valid_transition(current_mode: str, next_mode: str) -> bool:
    return next_mode in VALID_TRANSITIONS.get(current_mode or "idle", set())


def get_missing_params(collected_params: dict[str, Any], shape: str | None = None) -> list[str]:
    shape_value = shape or collected_params.get("shape")
    required = ["shape", "height", "width_a", "glass_type", "frame_color", "rows", "cols"]
    if shape_value in {"Г-образная", "П-образная"}:
        required.append("width_b")
    if shape_value == "П-образная":
        required.append("width_c")
    return [key for key in required if collected_params.get(key) in (None, "")]


def format_summary(collected_params: dict[str, Any]) -> str:
    labels = {
        "shape": "Форма",
        "height": "Высота",
        "width_a": "Ширина A",
        "width_b": "Ширина B",
        "width_c": "Ширина C",
        "glass_type": "Стекло",
        "frame_color": "Профиль",
        "rows": "Ряды",
        "cols": "Колонки",
        "frame_thickness": "Толщина рамы",
        "add_handle": "Ручка",
    }
    lines = ["<b>Параметры перегородки:</b>"]
    for key, label in labels.items():
        if key in collected_params and collected_params[key] not in (None, ""):
            lines.append(f"{label}: {collected_params[key]}")
    return "\n".join(lines)

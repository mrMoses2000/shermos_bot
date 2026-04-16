"""Finite State Machine for parameter collection."""

from __future__ import annotations

from typing import Any

from src.utils.json_tools import ensure_json_object

VALID_TRANSITIONS = {
    "idle": {"idle", "collecting", "scheduling"},
    "collecting": {"collecting", "confirming", "idle"},
    "confirming": {"rendering", "collecting", "idle"},
    "rendering": {"idle"},
    "scheduling": {"scheduling", "idle"},
}


def is_valid_transition(current_mode: str, next_mode: str) -> bool:
    return next_mode in VALID_TRANSITIONS.get(current_mode or "idle", set())


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "да", "нужна", "нужен", "нужно", "хочу"}
    return bool(value)


def get_missing_params(collected_params: dict[str, Any], shape: str | None = None) -> list[str]:
    collected_params = ensure_json_object(collected_params)
    shape_value = shape or collected_params.get("shape")
    required = [
        "shape",
        "partition_type",
        "height",
        "width_a",
        "glass_type",
        "frame_color",
        "matting",
        "add_handle",
        "rows",
        "cols",
    ]
    if shape_value in {"Г-образная", "П-образная"}:
        required.append("width_b")
    if shape_value == "Г-образная":
        required.append("shape_side")
    if shape_value == "П-образная":
        required.append("width_c")
    if _is_truthy(collected_params.get("add_handle")):
        required.append("handle_sections")
        if shape_value in {"Г-образная", "П-образная"}:
            required.append("handle_wall")
    return [key for key in required if collected_params.get(key) in (None, "")]


def format_summary(collected_params: dict[str, Any]) -> str:
    collected_params = ensure_json_object(collected_params)
    labels = {
        "shape": "Форма",
        "shape_side": "Боковая сторона",
        "partition_type": "Тип перегородки",
        "height": "Высота",
        "width_a": "Ширина A (основная/центральная)",
        "width_b": "Ширина B (боковая/левая)",
        "width_c": "Ширина C (правая боковая)",
        "glass_type": "Стекло",
        "frame_color": "Профиль",
        "matting": "Матировка",
        "complex_pattern": "Сложный рисунок вставок",
        "rows": "Ряды",
        "cols": "Колонки",
        "rows_front": "Ряды основной стены",
        "cols_front": "Колонки основной стены",
        "rows_side": "Ряды боковой стены",
        "cols_side": "Колонки боковой стены",
        "rows_left": "Ряды левой стены",
        "cols_left": "Колонки левой стены",
        "rows_right": "Ряды правой стены",
        "cols_right": "Колонки правой стены",
        "frame_thickness": "Толщина рамы",
        "add_handle": "Ручка",
        "handle_wall": "Стена ручки",
        "handle_sections": "Секции ручки",
    }
    lines = ["<b>Параметры перегородки:</b>"]
    for key, label in labels.items():
        if key in collected_params and collected_params[key] not in (None, ""):
            lines.append(f"{label}: {collected_params[key]}")
    return "\n".join(lines)

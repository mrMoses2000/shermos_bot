"""Price calculation engine."""

from __future__ import annotations

from typing import Any


def _area(shape: str, height: float, width_a: float, width_b: float = 0, width_c: float = 0) -> float:
    total_width = width_a
    if shape in {"Г-образная", "П-образная"}:
        total_width += width_b or 0
    if shape == "П-образная":
        total_width += width_c or 0
    return round(total_width * height, 3)


def calculate_price(
    shape: str,
    height: float,
    width_a: float,
    width_b: float = 0,
    width_c: float = 0,
    glass_type: str = "1",
    frame_color: str = "1",
    rows: int = 1,
    cols: int = 2,
    add_handle: bool = False,
) -> dict[str, Any]:
    area = _area(shape, height, width_a, width_b or 0, width_c or 0)
    base_rate_per_sqm = 180.0
    base_price = area * base_rate_per_sqm
    glass_modifier = 1.15 if str(glass_type) != "1" else 1.0
    frame_modifier = 1.04 if str(frame_color) not in {"1", "3"} else 1.0
    sections_modifier = 1 + max(0, (rows * cols) - 2) * 0.015
    subtotal = base_price * glass_modifier * frame_modifier * sections_modifier
    discount = subtotal * 0.06 if area > 8 else 0.0
    handle_price = 80.0 if add_handle else 0.0
    total = subtotal - discount + handle_price
    return {
        "total_price": round(total, 2),
        "currency": "USD",
        "details": {
            "area_sq_m": area,
            "base_rate_per_sqm": base_rate_per_sqm,
            "base_price": round(base_price, 2),
            "glass_modifier": glass_modifier,
            "frame_modifier": frame_modifier,
            "sections_modifier": round(sections_modifier, 3),
            "volume_discount": round(discount, 2),
            "handle_price": handle_price,
        },
    }

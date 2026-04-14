"""Price calculation engine."""

from __future__ import annotations

from typing import Any

from src.engine.pricing_cache import PricingCache, pricing_cache


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
    partition_type: str = "sliding_2",
    matting: str = "none",
    complex_pattern: bool = False,
    cache: PricingCache | None = None,
) -> dict[str, Any]:
    pc = cache or pricing_cache
    area = _area(shape, height, width_a, width_b or 0, width_c or 0)

    base_rate = pc.get_base_rate(partition_type, glass_type)
    base_price = area * base_rate

    matting_price = 0.0
    if matting != "none":
        matting_price = area * pc.get_addon_price(matting)

    pattern_price = 0.0
    if complex_pattern:
        pattern_price = area * pc.get_addon_price("complex_pattern")

    handle_price = pc.get_addon_price("handle") if add_handle else 0.0

    subtotal = base_price + matting_price + pattern_price

    frame_surcharge = 0.0
    if pc.is_frame_nonblack(frame_color):
        frame_surcharge = subtotal * pc.get_frame_modifier_pct()

    subtotal_with_frame = subtotal + frame_surcharge
    discount_rate, discount_threshold = pc.get_volume_discount()
    discount = subtotal_with_frame * discount_rate if area > discount_threshold else 0.0
    total = subtotal_with_frame - discount + handle_price

    return {
        "total_price": round(total, 2),
        "currency": "USD",
        "details": {
            "area_sq_m": area,
            "partition_type": partition_type,
            "base_rate_per_sqm": base_rate,
            "base_price": round(base_price, 2),
            "matting": matting,
            "matting_price": round(matting_price, 2),
            "complex_pattern_price": round(pattern_price, 2),
            "frame_surcharge": round(frame_surcharge, 2),
            "volume_discount": round(discount, 2),
            "handle_price": handle_price,
            "rows": rows,
            "cols": cols,
        },
    }

"""In-memory cache for pricing config from database."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from src.db import postgres
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_CACHE_TTL = 300

DEFAULT_PRICES: dict[str, dict[str, Any]] = {
    "base_fixed_standard": {
        "id": "base_fixed_standard",
        "name": "Стационарная — стандартное стекло",
        "category": "base",
        "amount": 130,
        "currency": "USD",
        "metadata": {"partition_type": "fixed", "glass_category": "standard", "unit": "sqm"},
    },
    "base_fixed_textured": {
        "id": "base_fixed_textured",
        "name": "Стационарная — рифлёное стекло",
        "category": "base",
        "amount": 150,
        "currency": "USD",
        "metadata": {"partition_type": "fixed", "glass_category": "textured", "unit": "sqm"},
    },
    "base_sliding2_standard": {
        "id": "base_sliding2_standard",
        "name": "Раздвижная 2 ств. — стандартное",
        "category": "base",
        "amount": 150,
        "currency": "USD",
        "metadata": {"partition_type": "sliding_2", "glass_category": "standard", "unit": "sqm"},
    },
    "base_sliding2_textured": {
        "id": "base_sliding2_textured",
        "name": "Раздвижная 2 ств. — рифлёное",
        "category": "base",
        "amount": 170,
        "currency": "USD",
        "metadata": {"partition_type": "sliding_2", "glass_category": "textured", "unit": "sqm"},
    },
    "base_sliding3_standard": {
        "id": "base_sliding3_standard",
        "name": "Раздвижная 3 ств. — стандартное",
        "category": "base",
        "amount": 160,
        "currency": "USD",
        "metadata": {"partition_type": "sliding_3", "glass_category": "standard", "unit": "sqm"},
    },
    "base_sliding3_textured": {
        "id": "base_sliding3_textured",
        "name": "Раздвижная 3 ств. — рифлёное",
        "category": "base",
        "amount": 180,
        "currency": "USD",
        "metadata": {"partition_type": "sliding_3", "glass_category": "textured", "unit": "sqm"},
    },
    "base_sliding4_standard": {
        "id": "base_sliding4_standard",
        "name": "Раздвижная 4 ств. — стандартное",
        "category": "base",
        "amount": 160,
        "currency": "USD",
        "metadata": {"partition_type": "sliding_4", "glass_category": "standard", "unit": "sqm"},
    },
    "base_sliding4_textured": {
        "id": "base_sliding4_textured",
        "name": "Раздвижная 4 ств. — рифлёное",
        "category": "base",
        "amount": 180,
        "currency": "USD",
        "metadata": {"partition_type": "sliding_4", "glass_category": "textured", "unit": "sqm"},
    },
    "addon_matting_solid": {
        "id": "addon_matting_solid",
        "name": "Сплошная матировка",
        "category": "addon",
        "amount": 7,
        "currency": "USD",
        "metadata": {"unit": "sqm", "addon_type": "matting_solid"},
    },
    "addon_matting_stripes": {
        "id": "addon_matting_stripes",
        "name": "Матовые полосы",
        "category": "addon",
        "amount": 12,
        "currency": "USD",
        "metadata": {"unit": "sqm", "addon_type": "matting_stripes"},
    },
    "addon_matting_logo": {
        "id": "addon_matting_logo",
        "name": "Матовый рисунок",
        "category": "addon",
        "amount": 19,
        "currency": "USD",
        "metadata": {"unit": "sqm", "addon_type": "matting_logo"},
    },
    "addon_complex_pattern": {
        "id": "addon_complex_pattern",
        "name": "Сложный рисунок вставок",
        "category": "addon",
        "amount": 3,
        "currency": "USD",
        "metadata": {"unit": "sqm", "addon_type": "complex_pattern"},
    },
    "addon_handle": {
        "id": "addon_handle",
        "name": "Дверная ручка",
        "category": "addon",
        "amount": 80,
        "currency": "USD",
        "metadata": {"unit": "piece", "addon_type": "handle"},
    },
    "mod_frame_nonblack": {
        "id": "mod_frame_nonblack",
        "name": "Наценка за цвет рамки",
        "category": "modifier",
        "amount": 4,
        "currency": "%",
        "metadata": {"description": "% к итогу за рамку не чёрного цвета"},
    },
    "mod_volume_discount": {
        "id": "mod_volume_discount",
        "name": "Скидка за объём",
        "category": "discount",
        "amount": 6,
        "currency": "%",
        "metadata": {"threshold_sqm": 8, "description": "% скидка при площади > 8 м²"},
    },
}

DEFAULT_MATERIALS: dict[str, dict[str, Any]] = {
    "glass_1": {
        "id": "glass_1",
        "kind": "glass",
        "name": "Прозрачное",
        "color": [0.85, 0.95, 1.0, 0.28],
        "roughness": 0.02,
        "metadata": {"source_id": "1"},
        "price_modifier": 1.0,
    },
    "glass_2": {
        "id": "glass_2",
        "kind": "glass",
        "name": "Серое",
        "color": [0.45, 0.5, 0.55, 0.35],
        "roughness": 0.04,
        "metadata": {"source_id": "2"},
        "price_modifier": 1.0,
    },
    "glass_3": {
        "id": "glass_3",
        "kind": "glass",
        "name": "Бронза",
        "color": [0.65, 0.45, 0.28, 0.35],
        "roughness": 0.04,
        "metadata": {"source_id": "3"},
        "price_modifier": 1.0,
    },
    "glass_4": {
        "id": "glass_4",
        "kind": "glass",
        "name": "Рифлёное",
        "color": [0.8, 0.9, 0.95, 0.42],
        "roughness": 0.22,
        "metadata": {"source_id": "4"},
        "price_modifier": 1.0,
    },
    "frame_1": {
        "id": "frame_1",
        "kind": "frame",
        "name": "Чёрный матовый",
        "color": [0.05, 0.05, 0.05, 1.0],
        "roughness": None,
        "metadata": {"source_id": "1"},
        "price_modifier": 1.0,
    },
    "frame_2": {
        "id": "frame_2",
        "kind": "frame",
        "name": "Белый глянцевый",
        "color": [0.95, 0.95, 0.92, 1.0],
        "roughness": None,
        "metadata": {"source_id": "2"},
        "price_modifier": 1.04,
    },
    "frame_3": {
        "id": "frame_3",
        "kind": "frame",
        "name": "Алюминий",
        "color": [0.65, 0.65, 0.62, 1.0],
        "roughness": None,
        "metadata": {"source_id": "3"},
        "price_modifier": 1.0,
    },
    "frame_4": {
        "id": "frame_4",
        "kind": "frame",
        "name": "Бронза",
        "color": [0.5, 0.32, 0.18, 1.0],
        "roughness": None,
        "metadata": {"source_id": "4"},
        "price_modifier": 1.04,
    },
    "frame_5": {
        "id": "frame_5",
        "kind": "frame",
        "name": "Золото",
        "color": [0.95, 0.72, 0.25, 1.0],
        "roughness": None,
        "metadata": {"source_id": "5"},
        "price_modifier": 1.04,
    },
}


def _default_prices() -> dict[str, dict[str, Any]]:
    return deepcopy(DEFAULT_PRICES)


def _default_materials() -> dict[str, dict[str, Any]]:
    return deepcopy(DEFAULT_MATERIALS)


class PricingCache:
    def __init__(self, ttl: int = _CACHE_TTL):
        self._ttl = ttl
        self._prices: dict[str, dict[str, Any]] = _default_prices()
        self._materials: dict[str, dict[str, Any]] = _default_materials()
        self._loaded_at: float = 0.0

    def is_stale(self) -> bool:
        return time.monotonic() - self._loaded_at > self._ttl

    async def ensure_loaded(self, pool) -> None:
        if self._prices and self._materials and not self.is_stale():
            return
        await self.reload(pool)

    async def reload(self, pool) -> None:
        prices_rows = await postgres.get_prices(pool)
        materials_rows = await postgres.get_materials(pool)
        self._prices = _default_prices()
        self._prices.update({row["id"]: row for row in prices_rows})
        self._materials = _default_materials()
        self._materials.update({row["id"]: row for row in materials_rows})
        self._loaded_at = time.monotonic()
        logger.info(
            "pricing_cache_reloaded",
            extra={"prices": len(self._prices), "materials": len(self._materials)},
        )

    def get_base_rate(self, partition_type: str, glass_type: str) -> float:
        """Get base rate from price matrix. glass_type "4" = textured, others = standard."""
        glass_cat = "textured" if str(glass_type) == "4" else "standard"
        normalized_partition = (partition_type or "sliding_2").replace("_", "")
        price_id = f"base_{normalized_partition}_{glass_cat}"
        row = self._prices.get(price_id)
        if row:
            return float(row["amount"])
        fallback = self._prices.get("base_sliding2_standard")
        return float(fallback["amount"]) if fallback else 150.0

    def get_addon_price(self, addon_type: str) -> float:
        """Get addon price by addon_type metadata."""
        for row in self._prices.values():
            meta = row.get("metadata") or {}
            if meta.get("addon_type") == addon_type:
                return float(row["amount"])
        return 0.0

    def get_frame_modifier_pct(self) -> float:
        """Returns frame non-black modifier as decimal, e.g. 0.04."""
        row = self._prices.get("mod_frame_nonblack")
        return float(row["amount"]) / 100.0 if row else 0.04

    def get_volume_discount(self) -> tuple[float, float]:
        """Returns (rate_decimal, threshold_sqm)."""
        row = self._prices.get("mod_volume_discount")
        if row:
            rate = float(row["amount"]) / 100.0
            threshold = float((row.get("metadata") or {}).get("threshold_sqm", 8))
            return rate, threshold
        return 0.06, 8.0

    def is_frame_nonblack(self, frame_color: str) -> bool:
        """Check if frame color has a price modifier > 1.0."""
        row = self._materials.get(f"frame_{frame_color}")
        if row and row.get("price_modifier") is not None:
            return float(row["price_modifier"]) > 1.001
        return str(frame_color) not in {"1", "3"}

    def get_glass_color(self, glass_type: str) -> list[float]:
        row = self._materials.get(f"glass_{glass_type}")
        return row["color"] if row and row.get("color") else [0.85, 0.85, 0.85, 0.3]

    def get_glass_roughness(self, glass_type: str) -> float:
        row = self._materials.get(f"glass_{glass_type}")
        return float(row["roughness"]) if row and row.get("roughness") is not None else 0.05

    def get_frame_color(self, frame_color: str) -> list[float]:
        row = self._materials.get(f"frame_{frame_color}")
        return row["color"] if row and row.get("color") else [0.05, 0.05, 0.05, 1.0]


pricing_cache = PricingCache()

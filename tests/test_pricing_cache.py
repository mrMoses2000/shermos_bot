import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from src.api import routes_pricing
from src.api.app import create_app
from src.api.deps import get_pool
from src.engine.pricing_cache import DEFAULT_MATERIALS, DEFAULT_PRICES, PricingCache
from src.engine.pricing_engine import calculate_price
from tests.helpers import signed_init_data


def _rows(data):
    return [deepcopy(row) for row in data.values()]


@pytest.mark.asyncio
async def test_cache_loads_from_db(monkeypatch):
    async def fake_get_prices(_pool):
        return _rows(DEFAULT_PRICES)

    async def fake_get_materials(_pool):
        return _rows(DEFAULT_MATERIALS)

    monkeypatch.setattr("src.engine.pricing_cache.postgres.get_prices", fake_get_prices)
    monkeypatch.setattr("src.engine.pricing_cache.postgres.get_materials", fake_get_materials)

    cache = PricingCache()
    await cache.reload(object())

    assert cache.get_base_rate("sliding_2", "1") == 150
    assert cache.get_frame_color("1") == DEFAULT_MATERIALS["frame_1"]["color"]


@pytest.mark.asyncio
async def test_cache_ttl_expired_reloads(monkeypatch):
    calls = 0
    cache = PricingCache(ttl=1)
    cache._loaded_at = time.monotonic() - 10

    async def fake_reload(_pool):
        nonlocal calls
        calls += 1
        cache._loaded_at = time.monotonic()

    monkeypatch.setattr(cache, "reload", fake_reload)

    await cache.ensure_loaded(object())

    assert calls == 1


def test_get_base_rate_matrix():
    cache = PricingCache()

    assert cache.get_base_rate("sliding_2", "1") == 150
    assert cache.get_base_rate("fixed", "4") == 150
    assert cache.get_base_rate("sliding_3", "2") == 160
    assert cache.get_base_rate("sliding_4", "4") == 180


def test_get_base_rate_fallback():
    cache = PricingCache()

    assert cache.get_base_rate("unknown", "1") == 150


def test_addon_price():
    cache = PricingCache()

    assert cache.get_addon_price("matting_solid") == 7
    assert cache.get_addon_price("handle") == 80


def test_frame_modifier():
    cache = PricingCache()

    assert cache.get_frame_modifier_pct() == 0.04
    assert cache.is_frame_nonblack("2")
    assert not cache.is_frame_nonblack("1")


def test_volume_discount():
    cache = PricingCache()

    assert cache.get_volume_discount() == (0.06, 8.0)


def test_calculate_price_fixed_standard():
    price = calculate_price(
        shape="Прямая",
        height=2,
        width_a=3,
        glass_type="1",
        frame_color="1",
        partition_type="fixed",
    )

    assert price["total_price"] == 780
    assert price["details"]["base_rate_per_sqm"] == 130


def test_calculate_price_sliding2_textured_with_matting():
    price = calculate_price(
        shape="Прямая",
        height=2,
        width_a=3,
        glass_type="4",
        frame_color="2",
        add_handle=True,
        partition_type="sliding_2",
        matting="matting_solid",
        complex_pattern=True,
    )

    assert price["details"]["base_price"] == 1020
    assert price["details"]["matting_price"] == 42
    assert price["details"]["complex_pattern_price"] == 18
    assert price["details"]["frame_surcharge"] == 43.2
    assert price["details"]["handle_price"] == 80
    assert price["total_price"] == 1203.2


def test_api_invalidates_cache(monkeypatch):
    async def fake_update_price(_pool, price_id, **fields):
        return {"id": price_id, **fields}

    monkeypatch.setattr(routes_pricing.postgres, "update_price", fake_update_price)
    routes_pricing.pricing_cache._loaded_at = 12345

    app = create_app()
    app.state.pg_pool = object()
    app.dependency_overrides[get_pool] = lambda: object()
    client = TestClient(app)

    response = client.patch(
        "/api/pricing/prices/base_fixed_standard",
        headers={"X-Telegram-Init-Data": signed_init_data()},
        json={"amount": 131},
    )

    assert response.status_code == 200
    assert routes_pricing.pricing_cache._loaded_at == 0

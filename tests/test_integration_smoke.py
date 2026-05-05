"""Integration smoke tests — require real Postgres and Redis on the server.

Run via: bash scripts/test_integration.sh
These tests are automatically SKIPPED locally (addopts = -m 'not integration').
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_select_one(pg_pool_integration):
    result = await pg_pool_integration.fetchval("SELECT 1")
    assert result == 1


@pytest.mark.asyncio
async def test_postgres_migrations_applied(pg_pool_integration):
    # All migrations should have created the core tables.
    rows = await pg_pool_integration.fetch(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'"
    )
    names = {r["tablename"] for r in rows}
    assert "outbound_events" in names
    assert "inbound_events" in names
    assert "measurements" in names


@pytest.mark.asyncio
async def test_redis_set_get(redis_client_integration):
    await redis_client_integration.client.set("test:smoke", "ok")
    val = await redis_client_integration.client.get("test:smoke")
    assert val.decode() == "ok"

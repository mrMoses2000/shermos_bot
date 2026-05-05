import os

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "client-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "client-secret")
os.environ.setdefault("MANAGER_BOT_TOKEN", "manager-token")
os.environ.setdefault("MANAGER_WEBHOOK_SECRET", "manager-secret")
os.environ.setdefault("POSTGRES_PASSWORD", "change_me")
os.environ.setdefault("LOG_FORMAT", "text")


@pytest.fixture(scope="session")
async def pg_pool_integration():
    """Real Postgres pool against the server's test DB. Skipped if INTEGRATION_DB_DSN is unset."""
    dsn = os.getenv("INTEGRATION_DB_DSN")
    if not dsn:
        pytest.skip("INTEGRATION_DB_DSN not set; integration tests run on server only")
    import asyncpg
    from src.db import postgres
    pool = await asyncpg.create_pool(dsn)
    try:
        await postgres.run_migrations(pool)
        yield pool
    finally:
        await pool.close()


@pytest.fixture(scope="session")
async def redis_client_integration():
    """Real Redis client with `test:` prefix. Skipped if INTEGRATION_REDIS_URL is unset."""
    url = os.getenv("INTEGRATION_REDIS_URL")
    if not url:
        pytest.skip("INTEGRATION_REDIS_URL not set; integration tests run on server only")
    from src.db.redis_client import RedisClient
    client = RedisClient(url, key_prefix="test:")
    await client.connect()
    try:
        yield client
    finally:
        # Wipe all test:* keys best-effort
        cursor = 0
        while True:
            cursor, keys = await client.client.scan(cursor=cursor, match="test:*", count=100)
            if keys:
                await client.client.delete(*keys)
            if cursor == 0:
                break
        await client.close()

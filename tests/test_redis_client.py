import pytest

from src.db.redis_client import RedisClient
from src.models import Job


class FakeRedisBackend:
    def __init__(self):
        self.items = []
        self.deleted = []
        self.cache = {}

    async def lpush(self, queue_name, payload):
        self.items.append((queue_name, payload))

    async def brpop(self, queue_name, timeout=5):
        if not self.items:
            return None
        _queue, payload = self.items.pop()
        return (queue_name, payload)

    async def set(self, key, value, nx=False, ex=None):
        self.cache[key] = value
        return True

    async def delete(self, key):
        self.deleted.append(key)

    async def get(self, key):
        return self.cache.get(key)


@pytest.mark.asyncio
async def test_redis_client_requires_connection():
    client = RedisClient("redis://localhost")

    with pytest.raises(RuntimeError):
        client._require_client()


@pytest.mark.asyncio
async def test_redis_queue_lock_and_cache():
    client = RedisClient("redis://localhost")
    backend = FakeRedisBackend()
    client.client = backend
    job = Job(update_id=1, chat_id=2, user_id=3, text="hi")

    await client.enqueue_job("queue", job)
    assert (await client.dequeue_job("queue")).update_id == 1
    assert await client.dequeue_job("queue") is None
    assert await client.acquire_user_lock(2) is True
    await client.release_user_lock(2)
    await client.set_cached("k", "v", 10)
    assert await client.get_cached("k") == "v"
    await client.delete_cached("k")

    assert "lock:user:2" in backend.deleted


@pytest.mark.asyncio
async def test_key_prefix_applied_to_enqueue():
    """RedisClient with key_prefix writes to prefixed key in Redis."""
    client = RedisClient("redis://localhost", key_prefix="t:")
    backend = FakeRedisBackend()
    client.client = backend
    job = Job(update_id=10, chat_id=20, user_id=30, text="prefixed")

    await client.enqueue_job("queue:foo", job)

    # The lpush must have been called with the prefixed key
    assert len(backend.items) == 1
    actual_key, _ = backend.items[0]
    assert actual_key == "t:queue:foo", f"Expected 't:queue:foo', got '{actual_key}'"


@pytest.mark.asyncio
async def test_no_key_prefix_by_default():
    """RedisClient without key_prefix writes to the bare key (no regression)."""
    client = RedisClient("redis://localhost")
    backend = FakeRedisBackend()
    client.client = backend
    job = Job(update_id=11, chat_id=21, user_id=31, text="no-prefix")

    await client.enqueue_job("queue:foo", job)

    assert len(backend.items) == 1
    actual_key, _ = backend.items[0]
    assert actual_key == "queue:foo", f"Expected 'queue:foo', got '{actual_key}'"


@pytest.mark.asyncio
async def test_key_prefix_applied_to_lock():
    """acquire_user_lock and release_user_lock use the prefix."""
    client = RedisClient("redis://localhost", key_prefix="t:")
    backend = FakeRedisBackend()
    client.client = backend

    await client.acquire_user_lock(99)
    assert "t:lock:user:99" in backend.cache

    await client.release_user_lock(99)
    assert "t:lock:user:99" in backend.deleted


@pytest.mark.asyncio
async def test_key_prefix_applied_to_cache():
    """set_cached / get_cached / delete_cached honour the prefix."""
    client = RedisClient("redis://localhost", key_prefix="t:")
    backend = FakeRedisBackend()
    client.client = backend

    await client.set_cached("mykey", "val", 60)
    assert "t:mykey" in backend.cache

    result = await client.get_cached("mykey")
    assert result == "val"

    await client.delete_cached("mykey")
    assert "t:mykey" in backend.deleted

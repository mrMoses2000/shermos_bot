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

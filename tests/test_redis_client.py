import json
from datetime import datetime, timedelta, timezone

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


# ---------------------------------------------------------------------------
# recover_stuck_jobs — max_age_seconds unit tests
# ---------------------------------------------------------------------------

class FakeRedisForRecovery:
    """Minimal fake that supports lpop, rpush, lpush."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    async def lpop(self, key: str) -> str | None:
        lst = self.lists.get(key, [])
        if not lst:
            return None
        return lst.pop(0)

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)


def _make_job_payload(received_at: datetime) -> str:
    """Return a JSON string that looks like a serialised Job with the given received_at."""
    return json.dumps({"received_at": received_at.isoformat(), "update_id": 1, "chat_id": 1})


@pytest.mark.asyncio
async def test_recover_stuck_jobs_no_max_age_moves_all():
    """Without max_age_seconds, all items are moved regardless of age."""
    client = RedisClient("redis://localhost")
    backend = FakeRedisForRecovery()
    client.client = backend

    fresh = datetime.now(timezone.utc)  # brand-new — would be skipped with max_age
    backend.lists["proc"] = [_make_job_payload(fresh)]

    moved = await client.recover_stuck_jobs("proc", "target")
    assert moved == 1
    assert backend.lists.get("target") == [_make_job_payload(fresh)]
    assert backend.lists.get("proc", []) == []


@pytest.mark.asyncio
async def test_recover_stuck_jobs_max_age_moves_only_old_jobs():
    """With max_age_seconds=300, only jobs older than 300 s are moved."""
    client = RedisClient("redis://localhost")
    backend = FakeRedisForRecovery()
    client.client = backend

    stale = datetime.now(timezone.utc) - timedelta(seconds=700)
    fresh = datetime.now(timezone.utc) - timedelta(seconds=10)

    # FIFO: stale is at the front (lpop returns it first)
    backend.lists["proc"] = [_make_job_payload(stale), _make_job_payload(fresh)]

    moved = await client.recover_stuck_jobs("proc", "target", max_age_seconds=300)
    assert moved == 1, "Only stale job should be moved"
    # Fresh job must remain in the processing list
    assert len(backend.lists.get("proc", [])) == 1


@pytest.mark.asyncio
async def test_recover_stuck_jobs_max_age_skips_fresh_at_front():
    """If the front job is fresh, scan stops immediately (none moved)."""
    client = RedisClient("redis://localhost")
    backend = FakeRedisForRecovery()
    client.client = backend

    fresh = datetime.now(timezone.utc) - timedelta(seconds=10)
    backend.lists["proc"] = [_make_job_payload(fresh)]

    moved = await client.recover_stuck_jobs("proc", "target", max_age_seconds=300)
    assert moved == 0
    # The job was put back
    assert len(backend.lists.get("proc", [])) == 1

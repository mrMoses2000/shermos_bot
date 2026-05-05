"""Redis queue, locks, and cache client."""

from __future__ import annotations

import json
import time
from typing import Optional

import redis.asyncio as redis

from src.models import Job


class RedisClient:
    def __init__(self, redis_url: str, key_prefix: str = ""):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.client: redis.Redis | None = None

    def _k(self, key: str) -> str:
        """Apply key_prefix to a Redis key."""
        return f"{self.key_prefix}{key}"

    async def connect(self) -> None:
        self.client = redis.from_url(self.redis_url, decode_responses=True)
        await self.client.ping()

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    def _require_client(self) -> redis.Redis:
        if self.client is None:
            raise RuntimeError("Redis client is not connected")
        return self.client

    async def enqueue_job(self, queue_name: str, job: Job) -> None:
        payload = job.model_dump_json()
        await self._require_client().lpush(self._k(queue_name), payload)

    async def dequeue_job(self, queue_name: str, timeout: int = 5) -> Optional[Job]:
        result = await self._require_client().brpop(self._k(queue_name), timeout=timeout)
        if not result:
            return None
        _queue, payload = result
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return Job.model_validate(json.loads(payload))

    async def dequeue_job_safe(self, queue_name: str, processing_name: str, timeout: int = 5) -> Optional[Job]:
        """Move a job from queue to processing list atomically before processing."""
        client = self._require_client()
        try:
            payload = await client.execute_command(
                "BLMOVE",
                self._k(queue_name),
                self._k(processing_name),
                "RIGHT",
                "LEFT",
                timeout,
            )
        except Exception:
            result = await client.brpop(self._k(queue_name), timeout=timeout)
            if not result:
                return None
            _queue, payload = result
            await client.lpush(self._k(processing_name), payload)
        if not payload:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return Job.model_validate(json.loads(payload))

    async def ack_job(self, processing_name: str, job: Job) -> None:
        """Remove a completed job from the processing list."""
        await self._require_client().lrem(self._k(processing_name), 1, job.model_dump_json())

    async def recover_stuck_jobs(self, processing_name: str, queue_name: str) -> int:
        """Move jobs left in processing back to the main queue on startup."""
        client = self._require_client()
        count = 0
        while True:
            payload = await client.rpoplpush(self._k(processing_name), self._k(queue_name))
            if payload is None:
                break
            count += 1
        return count

    async def schedule_job(self, delayed_name: str, job: Job, delay_seconds: float) -> None:
        """Schedule a job for later delivery without blocking the worker loop."""
        score = time.time() + max(0.0, delay_seconds)
        await self._require_client().zadd(self._k(delayed_name), {job.model_dump_json(): score})

    async def move_due_jobs(self, delayed_name: str, queue_name: str, limit: int = 100) -> int:
        """Move due delayed jobs back to the main Redis list."""
        client = self._require_client()
        payloads = await client.zrangebyscore(
            self._k(delayed_name),
            min="-inf",
            max=time.time(),
            start=0,
            num=limit,
        )
        if not payloads:
            return 0

        moved = 0
        async with client.pipeline(transaction=True) as pipe:
            for payload in payloads:
                pipe.zrem(self._k(delayed_name), payload)
                pipe.lpush(self._k(queue_name), payload)
            results = await pipe.execute()

        for index in range(0, len(results), 2):
            if results[index]:
                moved += 1
        return moved

    async def acquire_user_lock(self, chat_id: int, ttl: int = 180) -> bool:
        result = await self._require_client().set(self._k(f"lock:user:{chat_id}"), "1", nx=True, ex=ttl)
        return bool(result)

    async def release_user_lock(self, chat_id: int) -> None:
        await self._require_client().delete(self._k(f"lock:user:{chat_id}"))

    async def get_cached(self, key: str) -> Optional[str]:
        value = await self._require_client().get(self._k(key))
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    async def set_cached(self, key: str, value: str, ttl: int) -> None:
        await self._require_client().set(self._k(key), value, ex=ttl)

    async def delete_cached(self, key: str) -> None:
        await self._require_client().delete(self._k(key))

    async def rate_limit_check(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int]:
        """Fixed-window rate limiter. Returns (allowed, current_count).

        On the first hit within a window the key is created with a TTL of
        *window_seconds*.  Subsequent increments reuse the existing TTL so the
        window does not slide — it resets after the initial expiry.
        """
        client = self._require_client()
        count = await client.incr(self._k(key))
        if count == 1:
            await client.expire(self._k(key), window_seconds)
        return (count <= limit, count)

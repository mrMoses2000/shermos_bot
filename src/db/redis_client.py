"""Redis queue, locks, and cache client."""

from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as redis

from src.models import Job


class RedisClient:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client: redis.Redis | None = None

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
        await self._require_client().lpush(queue_name, payload)

    async def dequeue_job(self, queue_name: str, timeout: int = 5) -> Optional[Job]:
        result = await self._require_client().brpop(queue_name, timeout=timeout)
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
                queue_name,
                processing_name,
                "RIGHT",
                "LEFT",
                timeout,
            )
        except Exception:
            result = await client.brpop(queue_name, timeout=timeout)
            if not result:
                return None
            _queue, payload = result
            await client.lpush(processing_name, payload)
        if not payload:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return Job.model_validate(json.loads(payload))

    async def ack_job(self, processing_name: str, job: Job) -> None:
        """Remove a completed job from the processing list."""
        await self._require_client().lrem(processing_name, 1, job.model_dump_json())

    async def recover_stuck_jobs(self, processing_name: str, queue_name: str) -> int:
        """Move jobs left in processing back to the main queue on startup."""
        client = self._require_client()
        count = 0
        while True:
            payload = await client.rpoplpush(processing_name, queue_name)
            if payload is None:
                break
            count += 1
        return count

    async def acquire_user_lock(self, chat_id: int, ttl: int = 180) -> bool:
        result = await self._require_client().set(f"lock:user:{chat_id}", "1", nx=True, ex=ttl)
        return bool(result)

    async def release_user_lock(self, chat_id: int) -> None:
        await self._require_client().delete(f"lock:user:{chat_id}")

    async def get_cached(self, key: str) -> Optional[str]:
        value = await self._require_client().get(key)
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    async def set_cached(self, key: str, value: str, ttl: int) -> None:
        await self._require_client().set(key, value, ex=ttl)

    async def delete_cached(self, key: str) -> None:
        await self._require_client().delete(key)

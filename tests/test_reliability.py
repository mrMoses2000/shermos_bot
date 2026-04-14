import asyncio

import pytest

from src.db.redis_client import RedisClient
from src.engine import render_engine
from src.llm import health_check
from src.models import Job, RenderPartitionAction
from src.queue import outbox_dispatcher, worker


class SafeRedisBackend:
    def __init__(self, payloads=None):
        self.payloads = list(payloads or [])
        self.commands = []
        self.lrem_calls = []
        self.recovered = []

    async def execute_command(self, *args):
        self.commands.append(args)
        return self.payloads.pop(0) if self.payloads else None

    async def brpop(self, queue_name, timeout=5):
        return None

    async def lpush(self, queue_name, payload):
        self.commands.append(("LPUSH", queue_name, payload))

    async def lrem(self, processing_name, count, payload):
        self.lrem_calls.append((processing_name, count, payload))

    async def rpoplpush(self, processing_name, queue_name):
        if not self.recovered:
            return None
        self.commands.append(("RPOPLPUSH", processing_name, queue_name))
        return self.recovered.pop(0)


@pytest.mark.asyncio
async def test_dequeue_safe_moves_to_processing():
    job = Job(update_id=1, chat_id=2, user_id=3, text="hi")
    backend = SafeRedisBackend([job.model_dump_json()])
    client = RedisClient("redis://localhost")
    client.client = backend

    result = await client.dequeue_job_safe("queue:incoming", "queue:processing:client")

    assert result.update_id == 1
    assert backend.commands[0] == ("BLMOVE", "queue:incoming", "queue:processing:client", "RIGHT", "LEFT", 5)


@pytest.mark.asyncio
async def test_ack_job_removes_from_processing():
    job = Job(update_id=1, chat_id=2, user_id=3, text="hi")
    backend = SafeRedisBackend()
    client = RedisClient("redis://localhost")
    client.client = backend

    await client.ack_job("queue:processing:client", job)

    assert backend.lrem_calls == [("queue:processing:client", 1, job.model_dump_json())]


@pytest.mark.asyncio
async def test_recover_stuck_jobs_moves_back():
    backend = SafeRedisBackend()
    backend.recovered = ["a", "b"]
    client = RedisClient("redis://localhost")
    client.client = backend

    count = await client.recover_stuck_jobs("queue:processing:client", "queue:incoming")

    assert count == 2
    assert backend.commands == [
        ("RPOPLPUSH", "queue:processing:client", "queue:incoming"),
        ("RPOPLPUSH", "queue:processing:client", "queue:incoming"),
    ]


@pytest.mark.asyncio
async def test_client_loop_survives_redis_error(monkeypatch):
    calls = []

    class Redis:
        async def dequeue_job_safe(self, *_args, **_kwargs):
            calls.append("dequeue")
            if len(calls) == 1:
                raise RuntimeError("redis down")
            raise asyncio.CancelledError

    async def fake_sleep(seconds):
        calls.append(("sleep", seconds))

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker._client_loop(object(), Redis(), object())

    assert calls == ["dequeue", ("sleep", 5), "dequeue"]


@pytest.mark.asyncio
async def test_gemini_health_check_sets_flag(monkeypatch):
    sleeps = []

    async def fake_call_llm(_prompt):
        return '{"reply_text":"ok","actions":null}'

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError

    health_check._gemini_healthy = False
    monkeypatch.setattr(health_check, "call_llm", fake_call_llm)
    monkeypatch.setattr(health_check.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await health_check.run_gemini_health_check(interval=1)

    assert health_check.is_gemini_healthy() is True


@pytest.mark.asyncio
async def test_gemini_health_check_failure_sets_flag(monkeypatch):
    sleeps = []

    async def fake_call_llm(_prompt):
        raise RuntimeError("oauth expired")

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError

    health_check._gemini_healthy = True
    monkeypatch.setattr(health_check, "call_llm", fake_call_llm)
    monkeypatch.setattr(health_check.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await health_check.run_gemini_health_check(interval=1)

    assert health_check.is_gemini_healthy() is False


@pytest.mark.asyncio
async def test_outbox_skips_already_sent(monkeypatch):
    calls = []

    async def fake_get_pending(_pool, limit=20):
        return [{"id": 7, "chat_id": 10, "telegram_message_id": 99, "bot_type": "client"}]

    async def fake_mark_sent(_pool, event_id, telegram_message_id=None):
        calls.append(("sent", event_id, telegram_message_id))

    class Sender:
        async def send_message(self, *_args, **_kwargs):
            calls.append(("send",))

    monkeypatch.setattr(outbox_dispatcher.postgres, "get_pending_outbound", fake_get_pending)
    monkeypatch.setattr(outbox_dispatcher.postgres, "mark_outbound_sent", fake_mark_sent)

    sent = await outbox_dispatcher.dispatch_once(object(), Sender())

    assert sent == 0
    assert calls == [("sent", 7, 99)]


@pytest.mark.asyncio
async def test_render_timeout_kills_subprocess(monkeypatch, tmp_path):
    killed = []

    class Settings:
        renders_dir = str(tmp_path)

    class Process:
        pid = 123

        async def communicate(self):
            await asyncio.sleep(1)
            return b"", b""

        async def wait(self):
            return None

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(render_engine, "_RENDER_TIMEOUT", 0.01)
    monkeypatch.setattr(render_engine.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(render_engine.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(render_engine.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))

    params = RenderPartitionAction(shape="Прямая", height=2.5, width_a=3, glass_type="1", frame_color="1")

    with pytest.raises(TimeoutError, match="3D render timed out"):
        await render_engine.render_partition(params, "req-timeout", Settings())

    assert killed

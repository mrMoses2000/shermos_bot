import asyncio
import os
from unittest.mock import AsyncMock

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
    # Use the same _init_connection as production so jsonb codec is registered.
    pool = await asyncpg.create_pool(dsn, init=postgres._init_connection)
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


# ---------------------------------------------------------------------------
# Phase 4.2/4.3 integration fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def reset_integration_db(pg_pool_integration, redis_client_integration):
    """Truncate all tables and clear test:* Redis keys before each test."""
    await pg_pool_integration.execute(
        "TRUNCATE inbound_events, outbound_events, conversation_state, "
        "processed_updates, measurements, measurement_slots, "
        "gallery_works, gallery_photos RESTART IDENTITY CASCADE"
    )
    cursor = 0
    while True:
        cursor, keys = await redis_client_integration.client.scan(
            cursor=cursor, match="test:*", count=200
        )
        if keys:
            await redis_client_integration.client.delete(*keys)
        if cursor == 0:
            break
    yield


class FakeTelegramSender:
    """Records send_message calls; returns sequential fake message IDs."""

    channel = "telegram"

    def __init__(self):
        self.messages = []
        self.photos = []
        self.media_groups = []
        self.actions = []
        self._msg_counter = 0

    async def start(self):
        pass

    async def close(self):
        pass

    async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None, **kwargs):
        self._msg_counter += 1
        self.messages.append(
            {
                "token": token,
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )
        return self._msg_counter

    async def send_photo(self, token, chat_id, photo_path, caption=""):
        self.photos.append((token, chat_id, photo_path, caption))
        return {"ok": True}

    async def send_media_group(self, token, chat_id, photo_paths, caption=""):
        self.media_groups.append((token, chat_id, photo_paths, caption))
        return {"ok": True}

    async def send_chat_action(self, token, chat_id, action="typing"):
        self.actions.append((token, chat_id, action))
        return {"ok": True}


class FakeWhatsAppSender:
    """Records send_message / _post_json calls for WhatsApp; returns fake message IDs."""

    channel = "whatsapp"

    def __init__(self, role="client"):
        self.role = role
        self.messages = []
        self._post_calls = []
        self._msg_counter = 0
        self._raise = None  # set to an exception to simulate failures

    async def start(self):
        pass

    async def close(self):
        pass

    async def _post_json(self, path, payload):
        self._post_calls.append((path, payload))
        if self._raise:
            raise self._raise
        self._msg_counter += 1
        return {"message_id": f"fake-msg-{self._msg_counter}"}

    async def send_message(
        self,
        token,
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=None,
        idempotency_key=None,
        **kwargs,
    ):
        self._msg_counter += 1
        msg_id = f"fake-wa-{self._msg_counter}"
        self.messages.append(
            {
                "token": token,
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "idempotency_key": idempotency_key,
            }
        )
        if self._raise:
            raise self._raise
        return msg_id

    async def send_chat_action(self, token, chat_id, action="typing"):
        return {"ok": True}

    async def send_photo(self, token, chat_id, photo_path, caption=""):
        return {"ok": True}

    async def send_media_group(self, token, chat_id, photo_paths, caption=""):
        return {"ok": True}


@pytest.fixture
def mock_telegram_sender():
    """A FakeTelegramSender that records send_message calls."""
    return FakeTelegramSender()


@pytest.fixture
def mock_whatsapp_sender():
    """A FakeWhatsAppSender that records send_message calls (client role)."""
    return FakeWhatsAppSender(role="client")


@pytest.fixture
def mock_manager_whatsapp_sender():
    """A FakeWhatsAppSender that records send_message calls (manager role)."""
    return FakeWhatsAppSender(role="manager")


@pytest.fixture
def mock_call_llm(monkeypatch):
    """
    Patches src.llm.executor.call_llm to return a deterministic JSON response.

    Returns a list that tests can mutate:
      responses[0] = the JSON string that call_llm will return next.
    """
    responses = ['{"reply_text":"Принято.","actions":null}']

    async def _fake_call_llm(_prompt):
        return responses[0]

    import src.queue.worker as worker_mod
    monkeypatch.setattr(worker_mod, "call_llm", _fake_call_llm)

    # Also patch the apply_actions to avoid render/pricing side-effects
    async def _fake_apply_actions(*_args, **_kwargs):
        return {"render_paths": None, "price": None, "calendar_event": None, "order": None}

    monkeypatch.setattr(worker_mod, "apply_actions", _fake_apply_actions)
    return responses


@pytest.fixture
async def worker_running(
    pg_pool_integration,
    redis_client_integration,
    mock_telegram_sender,
):
    """
    Async generator fixture that starts _client_loop, _manager_loop, and
    run_outbox_dispatcher as background tasks with mocked senders.

    Yields control to the test; cancels all tasks on teardown.
    """
    from src.queue.worker import _client_loop, _manager_loop
    from src.queue.outbox_dispatcher import run_outbox_dispatcher

    tasks = [
        asyncio.create_task(
            _client_loop(pg_pool_integration, redis_client_integration, mock_telegram_sender)
        ),
        asyncio.create_task(
            _manager_loop(pg_pool_integration, redis_client_integration, mock_telegram_sender)
        ),
        asyncio.create_task(
            run_outbox_dispatcher(pg_pool_integration, mock_telegram_sender, interval=1)
        ),
    ]
    try:
        yield tasks
    finally:
        for task in tasks:
            task.cancel()
        # Await cancellation without raising
        await asyncio.gather(*tasks, return_exceptions=True)

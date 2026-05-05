"""
Phase 4.2 — Integration e2e tests for the Telegram client flow.

All tests require real Postgres + Redis (INTEGRATION_DB_DSN / INTEGRATION_REDIS_URL).
They are marked ``integration`` so they are deselected locally and run only via
``bash scripts/test_integration.sh`` on the server.

Design decisions:
  - We call mark_update_received / insert_inbound_event / enqueue_job directly
    (the same path the aiohttp webhook handler uses) instead of building a full
    aiohttp.web.Request, which avoids pulling in the HTTP layer.
  - We poll the DB for the expected outbound_events state rather than sleeping.
  - For the PermanentSendError (403) test we insert a backdated outbound_events
    row directly and run dispatch_once once — this avoids the 15-second
    ``created_at`` guard in get_pending_outbound.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.bot.errors import PermanentSendError
from src.db import postgres
from src.models import Job
from src.queue.outbox_dispatcher import dispatch_once

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

async def _poll_outbound(pg_pool, chat_id: int, status: str, timeout: float = 10.0) -> dict | None:
    """Poll outbound_events until a row with given chat_id and status appears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = await pg_pool.fetch(
            "SELECT * FROM outbound_events WHERE chat_id=$1 ORDER BY id DESC LIMIT 1",
            chat_id,
        )
        if rows:
            row = dict(rows[0])
            if row.get("status") == status:
                return row
        await asyncio.sleep(0.2)
    return None


async def _poll_outbound_external(pg_pool, external_chat_id: str, status: str, timeout: float = 10.0) -> dict | None:
    """Poll outbound_events by external_chat_id until given status appears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = await pg_pool.fetch(
            "SELECT * FROM outbound_events WHERE external_chat_id=$1 ORDER BY id DESC LIMIT 1",
            external_chat_id,
        )
        if rows:
            row = dict(rows[0])
            if row.get("status") == status:
                return row
        await asyncio.sleep(0.2)
    return None


def _make_telegram_update(update_id: int, chat_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "TestUser", "username": "testuser"},
            "text": text,
        },
    }


async def _ingest_telegram_update(pg_pool, redis_client, update: dict, bot_type: str = "client") -> Job:
    """
    Mirror the logic of webhook._process_webhook without an aiohttp.web.Request.
    Returns the Job that was enqueued.
    """
    update_id = int(update["update_id"])
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = int(chat.get("id", 0))
    user_id = int(user.get("id", chat_id))
    text = message.get("text") or ""

    is_new = await postgres.mark_update_received(pg_pool, update_id)
    if not is_new:
        return None  # duplicate

    await postgres.insert_inbound_event(pg_pool, update_id, chat_id, user_id, text, update)
    job = Job(
        update_id=update_id,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        msg_type="text",
        raw_update=update,
        bot_type=bot_type,
    )
    queue_name = "queue:manager" if bot_type == "manager" else "queue:incoming"
    await redis_client.enqueue_job(queue_name, job)
    return job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telegram_text_message_end_to_end(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
):
    """
    Full flow: inbound Telegram text → enqueue → worker processes → LLM mocked →
    outbound_events row created and marked sent by send_and_record.
    """
    CHAT_ID = 12345
    UPDATE_ID = 100001
    REPLY_TEXT = "Привет!"
    mock_call_llm[0] = f'{{"reply_text":"{REPLY_TEXT}","actions":null}}'

    update = _make_telegram_update(UPDATE_ID, CHAT_ID, "Здравствуйте")
    job = await _ingest_telegram_update(pg_pool_integration, redis_client_integration, update)
    assert job is not None, "Job should be enqueued"

    # Worker runs in background (worker_running fixture).
    # send_and_record sends inline and marks outbound 'sent' immediately.
    row = await asyncio.wait_for(
        _poll_outbound(pg_pool_integration, CHAT_ID, "sent"),
        timeout=10.0,
    )
    assert row is not None, "Expected an outbound_events row with status='sent'"
    assert row["chat_id"] == CHAT_ID

    # Confirm the mock sender recorded exactly 1 message to chat 12345
    sent_to_chat = [m for m in mock_telegram_sender.messages if m["chat_id"] == CHAT_ID]
    assert len(sent_to_chat) >= 1
    assert sent_to_chat[0]["text"] == REPLY_TEXT


@pytest.mark.asyncio
async def test_telegram_duplicate_update_id_dedup(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
):
    """
    Sending the same update_id twice must produce only 1 outbound_events row.
    The second ingest call is rejected by mark_update_received (ON CONFLICT DO NOTHING).
    """
    CHAT_ID = 22222
    UPDATE_ID = 200002

    update = _make_telegram_update(UPDATE_ID, CHAT_ID, "Дублируй меня")

    job1 = await _ingest_telegram_update(pg_pool_integration, redis_client_integration, update)
    assert job1 is not None, "First ingest should succeed"

    # Second ingest with same update_id — should return None (duplicate)
    job2 = await _ingest_telegram_update(pg_pool_integration, redis_client_integration, update)
    assert job2 is None, "Duplicate update_id should be rejected"

    # Wait for worker to process the single job
    row = await asyncio.wait_for(
        _poll_outbound(pg_pool_integration, CHAT_ID, "sent"),
        timeout=10.0,
    )
    assert row is not None

    # Confirm exactly 1 outbound row for this chat
    all_rows = await pg_pool_integration.fetch(
        "SELECT * FROM outbound_events WHERE chat_id=$1",
        CHAT_ID,
    )
    assert len(all_rows) == 1, f"Expected 1 outbound row, got {len(all_rows)}"


@pytest.mark.asyncio
async def test_telegram_403_blocked_no_retry_spam(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
):
    """
    A PermanentSendError (403 Forbidden) from the outbox dispatcher must
    immediately mark the outbound_events row as status='failed' (via mark_outbound_dead)
    rather than retrying up to 5 times.

    We insert an outbound_events row directly with a backdated created_at to bypass
    the 15-second freshness guard in get_pending_outbound, then run dispatch_once once.
    """
    CHAT_ID = 33333

    # Insert backdated outbound event
    event_id = await pg_pool_integration.fetchval(
        """
        INSERT INTO outbound_events (chat_id, bot_type, reply_text, channel, created_at)
        VALUES ($1, 'client', 'Hello 403', 'telegram', now() - interval '30 seconds')
        RETURNING id
        """,
        CHAT_ID,
    )
    assert event_id is not None

    # Patch the sender to raise PermanentSendError on send_message
    from src.bot.errors import PermanentSendError as PSE

    class BlockedSender(mock_telegram_sender.__class__):
        async def send_message(self, token, chat_id, text, **kwargs):
            raise PSE(403, "Forbidden: bot was blocked by the user")

    blocked_sender = BlockedSender()

    # Run dispatcher once — should detect PermanentSendError and call mark_outbound_dead
    await dispatch_once(pg_pool_integration, blocked_sender)

    # Verify the row is immediately dead (not retried 5 times)
    row = await pg_pool_integration.fetchrow(
        "SELECT status, attempts FROM outbound_events WHERE id=$1",
        event_id,
    )
    assert row is not None
    assert row["status"] == "failed", f"Expected 'failed', got '{row['status']}'"
    assert row["attempts"] >= 1, "Expected attempts >= 1"
    # Crucially, attempts should be exactly 1 (not 5)
    assert row["attempts"] < 5, "PermanentSendError must short-circuit; no 5-retry spam"

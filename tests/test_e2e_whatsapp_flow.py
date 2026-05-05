"""
Phase 4.3 — Integration e2e tests for the WhatsApp client flow.

All tests require real Postgres + Redis (INTEGRATION_DB_DSN / INTEGRATION_REDIS_URL).
Marked ``integration`` so they are deselected locally.

Design decisions:
  - We call enqueue_whatsapp_inbound directly (the same function that the aiohttp and
    FastAPI routes delegate to) rather than building a full HTTP request.
  - We patch src.queue.worker module-level globals (whatsapp_sender,
    manager_whatsapp_sender) to use FakeWhatsAppSender so no real bridge is called.
  - The worker_running fixture is used for tests that need the full loop.
  - For the outbox-dispatcher test we insert a row directly (with backdated
    created_at) and run dispatch_once once.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.bot.whatsapp_ingress import enqueue_whatsapp_inbound
from src.db import postgres
from src.queue.outbox_dispatcher import dispatch_once
from tests.conftest import FakeWhatsAppSender

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

async def _poll_outbound_external(
    pg_pool,
    external_chat_id: str,
    status: str,
    timeout: float = 10.0,
) -> dict | None:
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


async def _poll_outbound_chat(
    pg_pool,
    chat_id: int,
    status: str,
    timeout: float = 10.0,
) -> dict | None:
    """Poll outbound_events by chat_id (telegram channel) until given status appears."""
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


def _wa_payload(
    *,
    external_id: str,
    phone_e164: str,
    text: str = "Здравствуйте",
    msg_type: str = "text",
    bridge_role: str = "client",
) -> dict:
    return {
        "external_id": external_id,
        "phone_e164": phone_e164,
        "text": text,
        "msg_type": msg_type,
        "bridge_role": bridge_role,
        "external_chat_id": f"{phone_e164}@s.whatsapp.net",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whatsapp_client_on_client_number_routes_to_client_queue(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
    monkeypatch,
):
    """
    A regular client message on the client WhatsApp number must:
      - insert an inbound_event with channel='whatsapp'
      - route to queue:incoming (not queue:manager)
      - result in an outbound_events row with status='sent' and bot_type='client'
    """
    phone = "70001112233"
    external_id = "wa-client-001"
    # Inbound uses JID form; outbound external_chat_id is str(job.chat_id) = phone digits
    inbound_external_chat_id = f"{phone}@s.whatsapp.net"
    outbound_external_chat_id = phone  # send_and_record stores str(job.chat_id)

    # Patch whatsapp_sender in worker module so no real bridge call is made
    fake_wa = FakeWhatsAppSender(role="client")
    import src.queue.worker as worker_mod
    import src.bot.sender_common as sender_common_mod
    monkeypatch.setattr(worker_mod, "whatsapp_sender", fake_wa)
    monkeypatch.setattr(sender_common_mod, "whatsapp_sender", fake_wa)

    payload = _wa_payload(
        external_id=external_id,
        phone_e164=phone,
        text="Хочу перегородку",
        bridge_role="client",
    )
    result = await enqueue_whatsapp_inbound(pg_pool_integration, redis_client_integration, payload)
    assert result["queued"] is True
    assert result["duplicate"] is False

    # Verify inbound_events row has channel='whatsapp'
    inbound_rows = await pg_pool_integration.fetch(
        "SELECT * FROM inbound_events WHERE external_chat_id=$1",
        inbound_external_chat_id,
    )
    assert len(inbound_rows) == 1
    assert inbound_rows[0]["channel"] == "whatsapp"

    # Wait for worker to process and outbound to be created+sent
    # outbound_events.external_chat_id = str(job.chat_id) = phone digits (no JID suffix)
    row = await asyncio.wait_for(
        _poll_outbound_external(pg_pool_integration, outbound_external_chat_id, "sent"),
        timeout=10.0,
    )
    assert row is not None, "Expected outbound_events row with status='sent'"
    assert row["bot_type"] == "client"
    assert row["channel"] == "whatsapp"

    # Confirm fake sender received the message (worker passes job.chat_id as int)
    assert len(fake_wa.messages) >= 1
    assert fake_wa.messages[0]["chat_id"] == int(phone)


@pytest.mark.asyncio
async def test_whatsapp_client_on_manager_number_still_routes_to_client_queue(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
    monkeypatch,
):
    """
    A client writing to the MANAGER WhatsApp number (bridge_role='manager') but
    whose phone is NOT in the manager allowlist must still route to queue:incoming
    with bot_type='client'.  (Phase 1.2 fix: no whatsapp_manager_not_allowlisted error.)
    """
    phone = "70009998877"  # NOT in manager allowlist
    external_id = "wa-client-on-mgr-002"
    # Inbound uses JID form; outbound external_chat_id is str(job.chat_id) = phone digits
    inbound_external_chat_id = f"{phone}@s.whatsapp.net"
    outbound_external_chat_id = phone  # send_and_record stores str(job.chat_id)

    fake_wa = FakeWhatsAppSender(role="client")
    import src.queue.worker as worker_mod
    import src.bot.sender_common as sender_common_mod
    monkeypatch.setattr(worker_mod, "whatsapp_sender", fake_wa)
    monkeypatch.setattr(sender_common_mod, "whatsapp_sender", fake_wa)

    payload = _wa_payload(
        external_id=external_id,
        phone_e164=phone,
        text="Есть вопрос по цене",
        bridge_role="manager",  # incoming on manager number
    )
    result = await enqueue_whatsapp_inbound(pg_pool_integration, redis_client_integration, payload)
    assert result["queued"] is True

    # bot_type must be 'client' (sender is not in allowlist)
    inbound_rows = await pg_pool_integration.fetch(
        "SELECT * FROM inbound_events WHERE external_chat_id=$1",
        inbound_external_chat_id,
    )
    assert len(inbound_rows) == 1
    assert inbound_rows[0]["channel"] == "whatsapp"

    # Outbound should be created as 'client' bot_type
    # outbound_events.external_chat_id = str(job.chat_id) = phone digits (no JID suffix)
    row = await asyncio.wait_for(
        _poll_outbound_external(pg_pool_integration, outbound_external_chat_id, "sent"),
        timeout=10.0,
    )
    assert row is not None, "Expected outbound_events row with status='sent'"
    assert row["bot_type"] == "client", (
        f"Expected bot_type='client' for non-allowlist sender, got '{row['bot_type']}'"
    )


@pytest.mark.asyncio
async def test_whatsapp_staff_routes_to_manager_queue(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    mock_telegram_sender,
    mock_call_llm,
    worker_running,
    monkeypatch,
):
    """
    A sender whose phone IS in manager_whatsapp_numbers must be routed to
    queue:manager with bot_type='manager', regardless of bridge_role.
    """
    staff_phone = "70007776655"

    # Patch settings so this phone is considered staff
    import src.config as config_mod
    import src.bot.whatsapp_ingress as ingress_mod
    monkeypatch.setattr(config_mod.settings, "manager_whatsapp_numbers", staff_phone)
    # Also patch the ingress module's reference to settings
    monkeypatch.setattr(ingress_mod.settings, "manager_whatsapp_numbers", staff_phone)

    external_id = "wa-staff-003"
    # Inbound uses JID form; outbound external_chat_id is str(job.chat_id) = phone digits
    inbound_external_chat_id = f"{staff_phone}@s.whatsapp.net"
    outbound_external_chat_id = staff_phone  # send_and_record stores str(job.chat_id)

    fake_mgr_wa = FakeWhatsAppSender(role="manager")
    import src.queue.worker as worker_mod
    import src.bot.sender_common as sender_common_mod
    monkeypatch.setattr(worker_mod, "manager_whatsapp_sender", fake_mgr_wa)
    monkeypatch.setattr(sender_common_mod, "manager_whatsapp_sender", fake_mgr_wa)

    payload = _wa_payload(
        external_id=external_id,
        phone_e164=staff_phone,
        text="/health",
        bridge_role="client",  # incoming on client number but sender IS staff
    )
    result = await enqueue_whatsapp_inbound(pg_pool_integration, redis_client_integration, payload)
    assert result["queued"] is True

    # The inbound_event should exist
    inbound_rows = await pg_pool_integration.fetch(
        "SELECT * FROM inbound_events WHERE external_chat_id=$1",
        inbound_external_chat_id,
    )
    assert len(inbound_rows) == 1

    # Wait for manager outbound
    # outbound_events.external_chat_id = str(job.chat_id) = phone digits (no JID suffix)
    row = await asyncio.wait_for(
        _poll_outbound_external(pg_pool_integration, outbound_external_chat_id, "sent"),
        timeout=10.0,
    )
    assert row is not None, "Expected outbound_events row with status='sent'"
    assert row["bot_type"] == "manager", (
        f"Expected bot_type='manager' for staff sender, got '{row['bot_type']}'"
    )


@pytest.mark.asyncio
async def test_whatsapp_outbox_uses_manager_whatsapp_sender(
    pg_pool_integration,
    redis_client_integration,
    reset_integration_db,
    monkeypatch,
):
    """
    The outbox dispatcher must use manager_whatsapp_sender for outbound_events
    with channel='whatsapp' and bot_type='manager'.

    We insert a backdated outbound_events row directly and run dispatch_once once.
    """
    manager_chat_id = 77001234567
    external_chat_id = "77001234567@s.whatsapp.net"

    # Insert a backdated pending outbound event for manager whatsapp
    event_id = await pg_pool_integration.fetchval(
        """
        INSERT INTO outbound_events (
            chat_id, bot_type, reply_text, channel, external_chat_id,
            idempotency_key, created_at
        )
        VALUES ($1, 'manager', 'test manager message', 'whatsapp', $2, $3,
                now() - interval '30 seconds')
        RETURNING id
        """,
        manager_chat_id,
        external_chat_id,
        "test-idempotency-outbox-001",
    )
    assert event_id is not None

    fake_mgr_wa = FakeWhatsAppSender(role="manager")
    import src.queue.outbox_dispatcher as dispatcher_mod
    monkeypatch.setattr(dispatcher_mod, "manager_whatsapp_sender", fake_mgr_wa)

    # Run dispatcher once — should pick up the backdated pending event
    from src.bot.telegram_sender import TelegramSender

    class NoopTelegramSender(TelegramSender):
        """A telegram sender that never actually calls the API."""
        async def send_message(self, token, chat_id, text, **kwargs):
            return 9999

    await dispatch_once(pg_pool_integration, NoopTelegramSender())

    # Verify: the outbound_events row must now be 'sent'
    row = await pg_pool_integration.fetchrow(
        "SELECT status, external_message_id FROM outbound_events WHERE id=$1",
        event_id,
    )
    assert row is not None
    assert row["status"] == "sent", f"Expected 'sent', got '{row['status']}'"

    # Verify the fake manager sender was called with the correct chat_id
    assert len(fake_mgr_wa.messages) >= 1
    assert fake_mgr_wa.messages[0]["chat_id"] == external_chat_id

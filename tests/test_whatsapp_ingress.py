import pytest
from fastapi.testclient import TestClient

from src.api import routes_whatsapp
from src.api.app import create_app
from src.bot import whatsapp_ingress


class FakeRedis:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, queue_name, job):
        self.jobs.append((queue_name, job))


@pytest.mark.asyncio
async def test_enqueue_whatsapp_inbound_enqueues_channel_job(monkeypatch):
    calls = {}
    redis = FakeRedis()
    # Ensure the test phone is not in the manager allowlist
    monkeypatch.setattr(whatsapp_ingress.settings, "manager_whatsapp_numbers", "")

    async def mark_external_update_received(_pool, channel, external_update_id, synthetic_update_id):
        calls["dedup"] = (channel, external_update_id, synthetic_update_id)
        return True

    async def insert_inbound_event(_pool, update_id, chat_id, user_id, text, raw_update, **kwargs):
        calls["inbound"] = (update_id, chat_id, user_id, text, raw_update, kwargs)
        return 1

    monkeypatch.setattr(
        whatsapp_ingress.postgres,
        "mark_external_update_received",
        mark_external_update_received,
    )
    monkeypatch.setattr(whatsapp_ingress.postgres, "insert_inbound_event", insert_inbound_event)

    result = await whatsapp_ingress.enqueue_whatsapp_inbound(
        object(),
        redis,
        {
            "external_id": "wa-msg-1",
            "external_chat_id": "77064264520@s.whatsapp.net",
            "phone_e164": "77064264520",
            "text": "Ты чмо",
            "msg_type": "text",
        },
    )

    assert result["queued"] is True
    assert calls["dedup"][0:2] == ("whatsapp", "wa-msg-1")
    assert calls["inbound"][5]["channel"] == "whatsapp"
    assert calls["inbound"][5]["external_message_id"] == "wa-msg-1"
    queue_name, job = redis.jobs[0]
    assert queue_name == "queue:incoming"
    assert job.channel == "whatsapp"
    assert job.chat_id == 77064264520
    assert job.text == "Ты чмо"
    assert job.bot_type == "client"


@pytest.mark.asyncio
async def test_enqueue_whatsapp_inbound_routes_allowlisted_manager(monkeypatch):
    calls = {}
    redis = FakeRedis()

    async def mark_external_update_received(_pool, channel, external_update_id, synthetic_update_id):
        calls["dedup"] = (channel, external_update_id, synthetic_update_id)
        return True

    async def insert_inbound_event(_pool, update_id, chat_id, user_id, text, raw_update, **kwargs):
        calls["inbound"] = (update_id, chat_id, user_id, text, raw_update, kwargs)
        return 1

    monkeypatch.setattr(whatsapp_ingress.settings, "manager_whatsapp_numbers", "77067396626")
    monkeypatch.setattr(
        whatsapp_ingress.postgres,
        "mark_external_update_received",
        mark_external_update_received,
    )
    monkeypatch.setattr(whatsapp_ingress.postgres, "insert_inbound_event", insert_inbound_event)

    result = await whatsapp_ingress.enqueue_whatsapp_inbound(
        object(),
        redis,
        {
            "external_id": "wa-manager-1",
            "external_chat_id": "77067396626@s.whatsapp.net",
            "phone_e164": "+7-706-739-66-26",
            "bridge_role": "manager",
            "text": "/health",
            "msg_type": "text",
        },
    )

    assert result["queued"] is True
    queue_name, job = redis.jobs[0]
    assert queue_name == "queue:manager"
    assert job.bot_type == "manager"
    assert job.channel == "whatsapp"
    assert job.chat_id == 77067396626
    assert job.text == "/health"


@pytest.mark.asyncio
async def test_enqueue_whatsapp_inbound_client_on_manager_number(monkeypatch):
    """Non-staff client writes to manager WA number → goes to queue:incoming, no error."""
    redis = FakeRedis()
    logged = []
    monkeypatch.setattr(whatsapp_ingress.settings, "manager_whatsapp_numbers", "77067396626")

    async def mark_external_update_received(*_args):
        return True

    async def insert_inbound_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(whatsapp_ingress.postgres, "mark_external_update_received", mark_external_update_received)
    monkeypatch.setattr(whatsapp_ingress.postgres, "insert_inbound_event", insert_inbound_event)

    result = await whatsapp_ingress.enqueue_whatsapp_inbound(
        object(),
        redis,
        {
            "external_id": "wa-client-on-mgr",
            "external_chat_id": "77060000000@s.whatsapp.net",
            "phone_e164": "77060000000",
            "bridge_role": "manager",
            "text": "Хочу перегородку",
        },
    )

    assert result["queued"] is True
    queue_name, job = redis.jobs[0]
    assert queue_name == "queue:incoming"
    assert job.bot_type == "client"
    assert job.bridge_role == "manager"


@pytest.mark.asyncio
async def test_enqueue_whatsapp_inbound_staff_on_client_number(monkeypatch):
    """Staff member writes on client WA number → goes to queue:manager (allowlist wins)."""
    redis = FakeRedis()
    monkeypatch.setattr(whatsapp_ingress.settings, "manager_whatsapp_numbers", "77067396626")

    async def mark_external_update_received(*_args):
        return True

    async def insert_inbound_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(whatsapp_ingress.postgres, "mark_external_update_received", mark_external_update_received)
    monkeypatch.setattr(whatsapp_ingress.postgres, "insert_inbound_event", insert_inbound_event)

    result = await whatsapp_ingress.enqueue_whatsapp_inbound(
        object(),
        redis,
        {
            "external_id": "wa-staff-on-client",
            "external_chat_id": "77067396626@s.whatsapp.net",
            "phone_e164": "+7-706-739-66-26",
            "bridge_role": "client",
            "text": "Подтверждаю замер",
        },
    )

    assert result["queued"] is True
    queue_name, job = redis.jobs[0]
    assert queue_name == "queue:manager"
    assert job.bot_type == "manager"
    assert job.bridge_role == "client"


@pytest.mark.asyncio
async def test_enqueue_whatsapp_inbound_skips_duplicate(monkeypatch):
    redis = FakeRedis()

    async def mark_external_update_received(*_args):
        return False

    async def insert_inbound_event(*_args, **_kwargs):
        raise AssertionError("duplicate should not insert")

    monkeypatch.setattr(
        whatsapp_ingress.postgres,
        "mark_external_update_received",
        mark_external_update_received,
    )
    monkeypatch.setattr(whatsapp_ingress.postgres, "insert_inbound_event", insert_inbound_event)

    result = await whatsapp_ingress.enqueue_whatsapp_inbound(
        object(),
        redis,
        {"external_id": "dupe", "external_chat_id": "1@s.whatsapp.net", "text": "hi"},
    )

    assert result["duplicate"] is True
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_enqueue_whatsapp_inbound_prefers_sender_pn_for_lid(monkeypatch):
    redis = FakeRedis()

    async def mark_external_update_received(*_args):
        return True

    async def insert_inbound_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(
        whatsapp_ingress.postgres,
        "mark_external_update_received",
        mark_external_update_received,
    )
    monkeypatch.setattr(whatsapp_ingress.postgres, "insert_inbound_event", insert_inbound_event)

    await whatsapp_ingress.enqueue_whatsapp_inbound(
        object(),
        redis,
        {
            "external_id": "lid-msg",
            "external_chat_id": "102353885757655@lid",
            "jid": "102353885757655@lid",
            "text": "hi",
            "raw": {"key": {"senderPn": "77713979524@s.whatsapp.net"}},
        },
    )

    job = redis.jobs[0][1]
    assert job.chat_id == 77713979524
    assert job.phone_e164 == "77713979524"
    assert job.external_chat_id == "77713979524@s.whatsapp.net"


@pytest.mark.asyncio
async def test_enqueue_whatsapp_inbound_overrides_stale_top_level_phone_for_lid(monkeypatch):
    redis = FakeRedis()

    async def mark_external_update_received(*_args):
        return True

    async def insert_inbound_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(
        whatsapp_ingress.postgres,
        "mark_external_update_received",
        mark_external_update_received,
    )
    monkeypatch.setattr(whatsapp_ingress.postgres, "insert_inbound_event", insert_inbound_event)

    await whatsapp_ingress.enqueue_whatsapp_inbound(
        object(),
        redis,
        {
            "external_id": "lid-msg-stale-phone",
            "external_chat_id": "102353885757655@lid",
            "jid": "102353885757655@lid",
            "phone_e164": "102353885757655",
            "msg_type": "voice",
            "raw": {"key": {"senderPn": "77713979524@s.whatsapp.net"}},
        },
    )

    job = redis.jobs[0][1]
    assert job.chat_id == 77713979524
    assert job.phone_e164 == "77713979524"
    assert job.external_chat_id == "77713979524@s.whatsapp.net"
    assert job.msg_type == "voice"


def test_bridge_secret_validation(monkeypatch):
    monkeypatch.setattr(whatsapp_ingress.settings, "bridge_shared_secret", "secret")

    assert whatsapp_ingress.is_bridge_secret_valid("secret") is True
    assert whatsapp_ingress.is_bridge_secret_valid("wrong") is False


def test_fastapi_whatsapp_ingress_route(monkeypatch):
    app = create_app()
    app.state.pg_pool = object()
    app.state.redis_client = FakeRedis()
    monkeypatch.setattr(routes_whatsapp.settings, "bridge_shared_secret", "secret")

    async def enqueue_whatsapp_inbound(_pool, _redis, payload):
        assert payload["external_id"] == "route-msg"
        return {"queued": True, "duplicate": False, "update_id": 123}

    monkeypatch.setattr(routes_whatsapp, "enqueue_whatsapp_inbound", enqueue_whatsapp_inbound)
    client = TestClient(app)

    response = client.post(
        "/internal/whatsapp/inbound",
        headers={"X-Bridge-Secret": "secret"},
        json={"external_id": "route-msg", "external_chat_id": "1@s.whatsapp.net"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "queued": True, "duplicate": False, "update_id": 123}

"""Phase 14: manager NL → LLM tool routing."""
import json
import pytest
from src.llm import manager_tools
from src.llm.manager_prompt_builder import build_manager_prompt
from datetime import datetime, timezone as tz_mod


def test_build_manager_prompt_includes_user_message():
    p = build_manager_prompt("что у нас по заказам?")
    assert "что у нас по заказам?" in p
    assert "list_recent_orders" in p


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_none():
    result = await manager_tools.dispatch(object(), "no_such_tool", {})
    assert result is None


class _FakePool:
    def __init__(self, orders=None, measurements=None):
        self._orders = orders or []
        self._measurements = measurements or []
    # postgres helpers are async — wrap returns


@pytest.mark.asyncio
async def test_list_recent_orders_formats_output(monkeypatch):
    from datetime import datetime
    fake = [
        {"request_id": "2fdb6a4b-05cb-4eba-bf1b-6c12cd7d0e74", "status": "scheduled",
         "chat_id": 77085766841, "created_at": datetime(2026, 5, 5, 13, 0),
         "price": {"total_price": 688.4, "currency": "USD"}},
    ]
    async def fake_list(*_args, **_kwargs):
        return fake
    monkeypatch.setattr(manager_tools.postgres, "list_orders", fake_list)
    out = await manager_tools.list_recent_orders(object(), {"limit": 5})
    assert "2fdb6a4b" in out
    assert "688.4 USD" in out
    assert "77085766841" in out
    assert "📅" in out


@pytest.mark.asyncio
async def test_get_order_details_not_found(monkeypatch):
    async def fake_list(*_args, **_kwargs):
        return []
    monkeypatch.setattr(manager_tools.postgres, "list_orders", fake_list)
    out = await manager_tools.get_order_details(object(), {"request_id": "abcdef"})
    assert "не найден" in out.lower()


@pytest.mark.asyncio
async def test_cancel_measurement_invalid_id():
    out = await manager_tools.cancel_measurement(object(), {"measurement_id": "abc"})
    assert "не понял" in out.lower()


@pytest.mark.asyncio
async def test_confirm_measurement_with_explicit_id(monkeypatch):
    """Master says 'подтверди замер 5' — tool flips status to 'confirmed'."""
    async def fake_update(_pool, mid, status, reason=""):
        assert status == "confirmed"
        return {"id": mid, "scheduled_time": datetime(2026, 5, 12, 15, 0, tzinfo=tz_mod.utc)}

    monkeypatch.setattr(
        "src.engine.measurement_service.update_measurement_status", fake_update,
    )
    out = await manager_tools.confirm_measurement(object(), {"measurement_id": 5})
    assert "✅" in out
    assert "#5" in out
    assert "подтверждён" in out.lower()


@pytest.mark.asyncio
async def test_confirm_measurement_falls_back_to_single_active(monkeypatch):
    """No measurement_id provided + only one active → use it. This is the
    'подтверждаю' shortcut right after a new-measurement notification."""
    async def fake_list(_pool, **_kwargs):
        return [{"id": 7}]

    async def fake_update(_pool, mid, status, reason=""):
        assert mid == 7
        return {"id": mid, "scheduled_time": datetime(2026, 5, 12, 15, 0, tzinfo=tz_mod.utc)}

    monkeypatch.setattr(manager_tools.postgres, "list_measurements", fake_list)
    monkeypatch.setattr(
        "src.engine.measurement_service.update_measurement_status", fake_update,
    )

    out = await manager_tools.confirm_measurement(object(), {})
    assert "#7" in out
    assert "подтверждён" in out.lower()


@pytest.mark.asyncio
async def test_confirm_measurement_ambiguous_when_multiple_active(monkeypatch):
    """No id + multiple active → asks the master to specify."""
    async def fake_list(_pool, **_kwargs):
        return [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(manager_tools.postgres, "list_measurements", fake_list)

    out = await manager_tools.confirm_measurement(object(), {})
    assert "несколько активных" in out.lower()
    assert "подтверди замер" in out.lower()


@pytest.mark.asyncio
async def test_confirm_measurement_no_active_returns_friendly_message(monkeypatch):
    async def fake_list(_pool, **_kwargs):
        return []

    monkeypatch.setattr(manager_tools.postgres, "list_measurements", fake_list)

    out = await manager_tools.confirm_measurement(object(), {})
    assert "нечего подтверждать" in out.lower()


@pytest.mark.asyncio
async def test_dispatch_routes_confirm_measurement_to_tool():
    """confirm_measurement must be in the TOOLS dispatch table."""
    assert "confirm_measurement" in manager_tools.TOOLS


def test_manager_prompt_documents_confirm_tool():
    """The system prompt must list confirm_measurement so Gemini knows to
    pick it for 'подтверждаю' / 'подтверди замер N'."""
    p = build_manager_prompt("подтверждаю")
    assert "confirm_measurement" in p
    assert "подтверждаю" in p


@pytest.mark.asyncio
async def test_propose_reschedule_creates_client_outbox(monkeypatch):
    """propose_reschedule tool produces a client outbox row + master receipt."""
    outbox_rows = []

    async def fake_propose(_pool, mid, *, new_date, new_time, timezone, reason):
        return {
            "id": mid,
            "client_chat_id": 110099,
            "scheduled_time": datetime(2026, 5, 6, 11, 0, tzinfo=tz_mod.utc),
            "pending_reschedule_at": datetime(2026, 5, 6, 17, 0, tzinfo=tz_mod.utc),
            "pending_reschedule_reason": reason,
        }

    async def fake_insert_outbound(
        _pool, *, chat_id, channel, external_chat_id, reply_text,
        bot_type, idempotency_key, **_kwargs
    ):
        outbox_rows.append({
            "chat_id": chat_id,
            "text": reply_text,
            "bot_type": bot_type,
            "idem": idempotency_key,
        })
        return 1

    import src.engine.measurement_service as svc_mod
    monkeypatch.setattr(svc_mod, "propose_reschedule", fake_propose)
    monkeypatch.setattr(manager_tools.postgres, "insert_outbound_event", fake_insert_outbound)

    out = await manager_tools.propose_reschedule(
        object(),
        {"measurement_id": 10, "new_time": "17:00", "reason": "не могу в это время"},
    )
    assert "замер #10" in out
    assert "17:00" in out
    assert len(outbox_rows) == 1
    assert outbox_rows[0]["chat_id"] == 110099
    assert outbox_rows[0]["bot_type"] == "client"
    assert "17:00" in outbox_rows[0]["text"]


@pytest.mark.asyncio
async def test_propose_reschedule_invalid_id_returns_error():
    out = await manager_tools.propose_reschedule(object(), {"measurement_id": "abc", "new_time": "17:00"})
    assert "не понял" in out.lower()


@pytest.mark.asyncio
async def test_propose_reschedule_missing_time_returns_error():
    out = await manager_tools.propose_reschedule(object(), {"measurement_id": 5, "new_time": ""})
    assert "не понял" in out.lower()


def test_manager_prompt_includes_propose_reschedule():
    p = build_manager_prompt("не могу на замере 10, предложи на 17:00")
    assert "propose_reschedule" in p
    assert "не могу" in p.lower()


def test_manager_prompt_has_propose_reschedule_example():
    p = build_manager_prompt("test")
    assert "propose_reschedule" in p
    assert "new_time" in p

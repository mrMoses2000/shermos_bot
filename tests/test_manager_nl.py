"""Phase 14: manager NL → LLM tool routing."""
import json
import pytest
from src.llm import manager_tools
from src.llm.manager_prompt_builder import build_manager_prompt


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

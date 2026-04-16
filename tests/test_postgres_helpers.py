from datetime import datetime

import pytest

from src.db import postgres


class FakePool:
    def __init__(self, fetchrow_result=None, fetch_result=None, fetchval_result=1):
        self.fetchrow_result = fetchrow_result
        self.fetch_result = fetch_result if fetch_result is not None else []
        self.fetchval_result = fetchval_result
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        return self.fetchrow_result

    async def fetch(self, query, *args):
        self.calls.append(("fetch", query, args))
        return self.fetch_result

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query, args))
        return self.fetchval_result

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return "OK"


def test_json_and_row_helpers():
    assert postgres._json(None) == {}
    assert postgres._json({"a": "б"}) == {"a": "б"}
    assert postgres._row_to_dict(None) is None
    assert postgres._row_to_dict({"a": 1}) == {"a": 1}
    assert postgres._row_to_dict(
        {"collected_params": '{"shape": "Г-образная"}'},
        object_fields=("collected_params",),
    ) == {"collected_params": {"shape": "Г-образная"}}
    assert postgres._rows_to_dicts([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


@pytest.mark.asyncio
async def test_processed_update_queries():
    pool = FakePool(fetchrow_result={"telegram_update_id": 1})
    assert await postgres.mark_update_received(pool, 1) is True
    pool.fetchrow_result = None
    assert await postgres.mark_update_received(pool, 2) is False
    await postgres.mark_update_status(pool, 1, "completed")
    assert pool.calls[-1][0] == "execute"


@pytest.mark.asyncio
async def test_inbound_outbound_queries_serialize_json():
    pool = FakePool(fetchval_result=42)

    inbound_id = await postgres.insert_inbound_event(pool, 1, 2, 3, "", {"hello": "world"})
    outbound_id = await postgres.insert_outbound_event(
        pool,
        chat_id=2,
        reply_text="reply",
        reply_markup={"k": 1},
        inbound_event_id=inbound_id,
    )

    assert inbound_id == 42
    assert outbound_id == 42
    assert pool.calls[0][2][-1] == {"hello": "world"}
    assert pool.calls[1][2][3] == {"k": 1}


@pytest.mark.asyncio
async def test_conversation_and_messages_queries():
    pool = FakePool(
        fetchrow_result={"chat_id": 1, "mode": "idle", "collected_params": '{"shape": "Прямая"}'},
        fetch_result=[{"text": "hi"}],
    )

    state = await postgres.upsert_conversation_state(pool, 1, "idle", None, {})
    fetched = await postgres.get_conversation_state(pool, 1)
    messages = await postgres.get_chat_messages(pool, 1, limit=1)
    await postgres.insert_chat_message(pool, 1, "user", "hi")
    await postgres.clear_chat_messages(pool, 1)
    pool.fetchrow_result = {"request_id": "draft-1", "chat_id": 1, "collected_params": '{"shape": "Прямая"}'}
    draft = await postgres.get_active_order_draft(pool, 1)
    upserted_draft = await postgres.upsert_order_draft(pool, 1, {"shape": "Прямая"})
    await postgres.mark_active_order_draft_rendered(pool, 1, "draft-1")

    assert state["mode"] == "idle"
    assert fetched["collected_params"] == {"shape": "Прямая"}
    assert draft["collected_params"] == {"shape": "Прямая"}
    assert upserted_draft["request_id"] == "draft-1"
    assert messages == [{"text": "hi"}]
    assert pool.calls[-1][0] == "execute"


@pytest.mark.asyncio
async def test_client_order_measurement_crud_queries():
    pool = FakePool(
        fetchrow_result={"chat_id": 10, "request_id": "r1", "id": 3},
        fetch_result=[{"status": "new"}],
    )

    assert (await postgres.create_client(pool, 10, "Ann", "ann"))["chat_id"] == 10
    assert (await postgres.update_client(pool, 10, name="Anna"))["chat_id"] == 10
    assert await postgres.list_clients(pool, search="ann") == [{"status": "new"}]
    assert (await postgres.create_order(pool, "r1", 10, {"a": 1}, {"0": "p"}, {"total": 1}))[
        "request_id"
    ] == "r1"
    assert await postgres.list_orders(pool, status="new", search="10") == [{"status": "new"}]
    assert (await postgres.update_order_status(pool, "r1", "confirmed"))["request_id"] == "r1"
    assert (await postgres.create_measurement(pool, 10, datetime.now(), "addr"))["id"] == 3
    assert await postgres.list_measurements(pool, upcoming_only=False) == [{"status": "new"}]


@pytest.mark.asyncio
async def test_not_found_paths_raise():
    pool = FakePool(fetchrow_result=None)

    with pytest.raises(ValueError):
        await postgres.update_order_status(pool, "missing", "new")
    with pytest.raises(ValueError):
        await postgres.confirm_measurement(pool, 123)
    with pytest.raises(ValueError):
        await postgres.update_price(pool, "missing")
    with pytest.raises(ValueError):
        await postgres.update_material(pool, "missing")


@pytest.mark.asyncio
async def test_price_material_and_dashboard_queries():
    pool = FakePool(fetchrow_result={"total_orders": 1, "total_revenue": 20.0, "orders_today": 1}, fetchval_result=2)
    pool.fetch_result = [{"id": "base"}, {"kind": "glass"}, {"status": "new", "count": 3}]

    assert await postgres.get_prices(pool) == pool.fetch_result
    assert (await postgres.update_price(pool, "base", amount=200))["total_orders"] == 1
    assert await postgres.get_materials(pool) == pool.fetch_result
    assert (await postgres.update_material(pool, "glass_1", name="Glass"))["total_orders"] == 1
    pool.fetch_result = [{"status": "new", "count": 3}]
    assert await postgres.count_orders_by_status(pool) == {"new": 3}
    assert (await postgres.get_dashboard_stats(pool))["pending_measurements"] == 2

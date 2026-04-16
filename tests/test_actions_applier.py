from types import SimpleNamespace

import pytest

from src.llm import actions_applier
from src.models import ActionsJson


@pytest.mark.asyncio
async def test_apply_actions_no_actions_returns_empty_result():
    result = await actions_applier.apply_actions(
        ActionsJson(reply_text="ok", actions=None),
        1,
        None,
        None,
        object(),
        object(),
        SimpleNamespace(),
    )

    assert result == {"render_paths": None, "price": None, "measurement": None, "order": None}


@pytest.mark.asyncio
async def test_apply_actions_updates_profile_and_state(monkeypatch):
    calls = []

    async def fake_update_client(_pool, chat_id, **fields):
        calls.append(("client", chat_id, fields))

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))

    async def fake_upsert_draft(_pool, chat_id, collected_params, status="collecting", request_id=None):
        calls.append(("draft", chat_id, collected_params, status, request_id))
        return {"request_id": request_id or "draft-1", "collected_params": collected_params}

    monkeypatch.setattr(actions_applier.postgres, "update_client", fake_update_client)
    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)

    actions = ActionsJson(
        reply_text="ok",
        actions={
            "update_client_profile": {"name": "Анна", "phone": "+1", "address": "Addr"},
            "state_patch": {
                "mode": "collecting",
                "step": "ask_glass",
                "collected_params": {"shape": "Прямая"},
            },
        },
    )

    await actions_applier.apply_actions(actions, 10, None, {"mode": "idle"}, object(), object(), SimpleNamespace())

    assert calls[0] == ("client", 10, {"name": "Анна", "phone": "+1", "address": "Addr"})
    assert calls[1] == ("state", 10, "collecting", "ask_glass", {"shape": "Прямая"})
    assert calls[2] == ("draft", 10, {"shape": "Прямая"}, "collecting", None)


@pytest.mark.asyncio
async def test_apply_actions_render_creates_order_and_notifies_manager(monkeypatch):
    calls = []

    async def fake_render_partition(params, request_id, settings):
        calls.append(("render", params.shape, request_id))
        return {"render_paths": {"0deg": "/tmp/a.png"}}

    async def fake_create_order(_pool, request_id, chat_id, details_json, render_paths, price):
        calls.append(("order", request_id, chat_id, details_json, render_paths, price))
        return {"request_id": request_id}

    async def fake_send_message(token, chat_id, text):
        calls.append(("manager_message", token, chat_id, text))
        return {"ok": True}

    async def fake_ensure_loaded(_pool):
        calls.append(("cache",))

    async def fake_get_active_draft(_pool, chat_id):
        calls.append(("get_draft", chat_id))
        return {"request_id": "request-1", "collected_params": {}}

    async def fake_upsert_draft(_pool, chat_id, collected_params, status="collecting", request_id=None):
        calls.append(("draft", chat_id, collected_params, status, request_id))
        return {"request_id": request_id or "request-1", "collected_params": collected_params}

    async def fake_mark_draft_rendered(_pool, chat_id, request_id):
        calls.append(("draft_rendered", chat_id, request_id))

    monkeypatch.setattr(actions_applier, "render_partition", fake_render_partition)
    monkeypatch.setattr(actions_applier.pricing_cache, "reload", fake_ensure_loaded)
    monkeypatch.setattr(actions_applier.postgres, "create_order", fake_create_order)
    monkeypatch.setattr(actions_applier.postgres, "get_active_order_draft", fake_get_active_draft)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)
    monkeypatch.setattr(actions_applier.postgres, "mark_active_order_draft_rendered", fake_mark_draft_rendered)
    monkeypatch.setattr(actions_applier.telegram_sender, "send_message", fake_send_message)
    monkeypatch.setattr(actions_applier, "uuid4", lambda: "request-1")

    settings = SimpleNamespace(manager_chat_ids_list=[99], manager_bot_token="manager")
    actions = ActionsJson(
        reply_text="ok",
        actions={
            "render_partition": {
                "shape": "Прямая",
                "height": 2.5,
                "width_a": 3,
                "partition_type": "sliding_2",
                "glass_type": "1",
                "frame_color": "1",
                "matting": "none",
                "add_handle": False,
                "rows": 1,
                "cols": 2,
            }
        },
    )

    result = await actions_applier.apply_actions(actions, 10, None, None, object(), object(), settings)

    assert result["order"]["request_id"] == "request-1"
    assert result["price"]["total_price"] > 0
    assert calls[-1][0] == "manager_message"
    assert ("draft_rendered", 10, "request-1") in calls


@pytest.mark.asyncio
async def test_apply_actions_blocks_render_until_required_fields(monkeypatch):
    calls = []

    async def fake_render_partition(*_args, **_kwargs):
        calls.append("render")
        return {"render_paths": {"0deg": "/tmp/a.png"}}

    monkeypatch.setattr(actions_applier, "render_partition", fake_render_partition)

    actions = ActionsJson(
        reply_text="ok",
        actions={
            "render_partition": {
                "shape": "Г-образная",
                "height": 2.5,
                "width_a": 3,
                "width_b": 1,
                "partition_type": "sliding_2",
                "glass_type": "1",
                "frame_color": "1",
                "matting": "none",
                "add_handle": False,
                "rows": 1,
                "cols": 2,
            }
        },
    )

    result = await actions_applier.apply_actions(actions, 10, None, None, object(), object(), SimpleNamespace())

    assert "shape_side" in result["render_missing_params"]
    assert calls == []


@pytest.mark.asyncio
async def test_apply_actions_schedule_measurement(monkeypatch):
    calls = []
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fake_measurement = {
        "id": 1,
        "client_chat_id": 10,
        "scheduled_time": datetime(2026, 4, 14, 10, 0, tzinfo=ZoneInfo("Asia/Bishkek")),
        "address": "Addr",
        "client_name": "Анна",
        "client_phone": "+1",
        "status": "scheduled",
    }

    async def fake_schedule_measurement(**kwargs):
        calls.append(("schedule", kwargs))
        return fake_measurement

    async def fake_update_client(_pool, chat_id, **fields):
        calls.append(("client", chat_id, fields))

    async def fake_send_message(token, chat_id, text, reply_markup=None):
        calls.append(("msg", token, chat_id))
        return {"ok": True}

    monkeypatch.setattr(actions_applier, "schedule_measurement", fake_schedule_measurement)
    monkeypatch.setattr(actions_applier.postgres, "update_client", fake_update_client)
    monkeypatch.setattr(actions_applier.telegram_sender, "send_message", fake_send_message)

    settings = SimpleNamespace(
        manager_chat_ids_list=[99],
        manager_bot_token="manager",
        telegram_bot_token="client",
        timezone="Asia/Bishkek",
    )
    actions = ActionsJson(
        reply_text="ok",
        actions={
            "schedule_measurement": {
                "date": "2026-04-14",
                "time": "10:00",
                "client_name": "Анна",
                "phone": "+1",
                "address": "Addr",
            }
        },
    )

    result = await actions_applier.apply_actions(actions, 10, None, None, object(), object(), settings)

    assert result["measurement"]["id"] == 1
    assert any(c[0] == "schedule" for c in calls)
    assert any(c[0] == "msg" for c in calls)  # manager was notified


@pytest.mark.asyncio
async def test_apply_actions_invalid_state_transition_stays_current(monkeypatch):
    calls = []

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append((chat_id, mode, step, collected_params))

    async def fake_upsert_draft(_pool, chat_id, collected_params, status="collecting", request_id=None):
        return {"request_id": request_id or "draft-1", "collected_params": collected_params}

    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)
    actions = ActionsJson(reply_text="ok", actions={"state_patch": {"mode": "rendering", "step": "bad"}})

    await actions_applier.apply_actions(actions, 10, None, {"mode": "idle"}, object(), object(), SimpleNamespace())

    assert calls == [(10, "idle", "bad", {})]


@pytest.mark.asyncio
async def test_apply_actions_state_patch_merges_existing_collected_params(monkeypatch):
    calls = []

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append((chat_id, mode, step, collected_params))

    async def fake_upsert_draft(_pool, chat_id, collected_params, status="collecting", request_id=None):
        return {"request_id": request_id or "draft-1", "collected_params": collected_params}

    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)
    actions = ActionsJson(
        reply_text="ok",
        actions={"state_patch": {"mode": "collecting", "step": "dims", "collected_params": {"width_a": 2}}},
    )

    await actions_applier.apply_actions(
        actions,
        10,
        None,
        {"mode": "collecting", "collected_params": '{"shape": "Г-образная"}'},
        object(),
        object(),
        SimpleNamespace(),
    )

    assert calls == [(10, "collecting", "dims", {"shape": "Г-образная", "width_a": 2})]

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

    async def fake_get_rendered_draft(_pool, chat_id):
        calls.append(("get_rendered_draft", chat_id))
        return None

    async def fake_upsert_draft(_pool, chat_id, collected_params, status="collecting", request_id=None):
        calls.append(("draft", chat_id, collected_params, status, request_id))
        return {"request_id": request_id or "request-1", "collected_params": collected_params}

    async def fake_mark_draft_rendered(_pool, chat_id, request_id):
        calls.append(("draft_rendered", chat_id, request_id))

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))

    monkeypatch.setattr(actions_applier, "render_partition", fake_render_partition)
    monkeypatch.setattr(actions_applier.pricing_cache, "reload", fake_ensure_loaded)
    monkeypatch.setattr(actions_applier.postgres, "create_order", fake_create_order)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)
    monkeypatch.setattr(actions_applier.postgres, "get_active_order_draft", fake_get_active_draft)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)
    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
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
    assert any(call[0] == "manager_message" for call in calls)
    assert ("draft_rendered", 10, "request-1") in calls
    assert ("get_rendered_draft", 10) in calls


@pytest.mark.asyncio
async def test_apply_actions_reuses_existing_rendered_order(monkeypatch):
    calls = []

    async def fake_render_partition(*_args, **_kwargs):
        calls.append("render")
        return {"render_paths": {"0deg": "/tmp/a.png"}}

    async def fake_create_order(*_args, **_kwargs):
        calls.append("order")
        return {"request_id": "new-order"}

    async def fake_get_rendered_draft(_pool, chat_id):
        assert chat_id == 10
        return {
            "request_id": "draft-1",
            "chat_id": 10,
            "status": "rendered",
            "rendered_order_id": "order-1",
            "order_status": "new",
            "details_json": {
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
            },
            "render_paths": {"0deg": "/tmp/a.png"},
            "price": {"total_price": 100, "currency": "USD"},
            "collected_params": {"shape": "Прямая"},
        }

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))

    async def fake_upsert_draft(*_args, **_kwargs):
        calls.append("draft")
        return {}

    monkeypatch.setattr(actions_applier, "render_partition", fake_render_partition)
    monkeypatch.setattr(actions_applier.postgres, "create_order", fake_create_order)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)
    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)

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
            },
            "state_patch": {"mode": "scheduling", "step": "ask_time", "collected_params": {}},
        },
    )

    result = await actions_applier.apply_actions(
        actions,
        10,
        None,
        {"mode": "rendering", "collected_params": {"shape": "Прямая"}},
        object(),
        object(),
        SimpleNamespace(),
    )

    assert result["render_reused"] is True
    assert result["render_paths"] == {"0deg": "/tmp/a.png"}
    assert result["price"] == {"total_price": 100, "currency": "USD"}
    assert "render" not in calls

@pytest.mark.asyncio
async def test_render_reuse_rejects_stale_rendered_order_when_params_changed(monkeypatch):
    calls = []

    async def fake_render_partition(*_args, **_kwargs):
        calls.append("render")
        return {"render_paths": {"0deg": "/tmp/new.png"}}

    async def fake_create_order(*_args, **_kwargs):
        calls.append("order")
        return {"request_id": "new-order"}

    async def fake_get_rendered_draft(_pool, chat_id):
        return {
            "request_id": "draft-1",
            "chat_id": 10,
            "status": "rendered",
            "rendered_order_id": "order-1",
            "order_status": "new",
            "details_json": {
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
            },
            "render_paths": {"0deg": "/tmp/a.png"},
            "price": {"total_price": 100, "currency": "USD"},
            "collected_params": {"shape": "Прямая"},
        }

    async def fake_get_active_draft(*_args, **_kwargs):
        return {"request_id": "draft-1"}

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))

    async def fake_upsert_draft(*_args, **_kwargs):
        calls.append("draft")
        return {}

    async def fake_mark_draft_rendered(*_args, **_kwargs):
        pass

    async def fake_reload(*args, **kwargs):
        pass

    def fake_calculate_price(*args, **kwargs):
        return {"total_price": 200, "currency": "USD"}

    monkeypatch.setattr(actions_applier, "render_partition", fake_render_partition)
    monkeypatch.setattr(actions_applier.postgres, "create_order", fake_create_order)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)
    monkeypatch.setattr(actions_applier.postgres, "get_active_order_draft", fake_get_active_draft)
    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)
    monkeypatch.setattr(actions_applier.postgres, "mark_active_order_draft_rendered", fake_mark_draft_rendered)
    monkeypatch.setattr(actions_applier.pricing_cache, "reload", fake_reload)
    monkeypatch.setattr(actions_applier, "calculate_price", fake_calculate_price)
    monkeypatch.setattr(actions_applier.telegram_sender, "send_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(actions_applier, "_send_manager_whatsapp_notification", lambda *args, **kwargs: None)

    settings = SimpleNamespace(manager_chat_ids_list=[], manager_bot_token="manager", manager_whatsapp_numbers_list=[])

    actions = ActionsJson(
        reply_text="ok",
        actions={
            "render_partition": {
                "shape": "Г-образная", # CHANGED PARAMETER
                "height": 2.5,
                "width_a": 3,
                "width_b": 1,
                "shape_side": "left",
                "partition_type": "sliding_2",
                "glass_type": "1",
                "frame_color": "1",
                "matting": "none",
                "add_handle": False,
                "rows": 1,
                "cols": 2,
            },
            "state_patch": {"mode": "rendering", "step": "ask_time", "collected_params": {"_rendered_order_id": "order-1"}},
        },
    )

    result = await actions_applier.apply_actions(
        actions,
        10,
        None,
        {"mode": "rendering", "collected_params": {"_rendered_order_id": "order-1"}},
        object(),
        object(),
        settings,
    )

    assert result.get("render_reused") is not True
    assert result["render_paths"] == {"0deg": "/tmp/new.png"}
    assert "render" in calls
    # Make sure stale binding is removed from state patch if any
    for call in calls:
        if call[0] == "state":
            assert "_rendered_order_id" not in call[4] or call[4]["_rendered_order_id"] != "order-1"
    assert result["order"]["request_id"] == "new-order"
    assert "render" in calls
    assert "order" in calls


@pytest.mark.asyncio
async def test_apply_actions_blocks_render_until_required_fields(monkeypatch):
    calls = []

    async def fake_render_partition(*_args, **_kwargs):
        calls.append("render")
        return {"render_paths": {"0deg": "/tmp/a.png"}}

    async def fake_get_rendered_draft(*_args, **_kwargs):
        return None

    monkeypatch.setattr(actions_applier, "render_partition", fake_render_partition)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)

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

    async def fake_get_rendered_draft(_pool, chat_id):
        assert chat_id == 10
        return None

    monkeypatch.setattr(actions_applier, "schedule_measurement", fake_schedule_measurement)
    monkeypatch.setattr(actions_applier.postgres, "update_client", fake_update_client)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)
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
            },
            "state_patch": {
                "mode": "scheduling",
                "step": "measurement_ready",
                "collected_params": {
                    "measurement_date": "2026-04-14",
                    "measurement_time": "10:00",
                    "measurement_name": "Анна",
                    "measurement_phone": "+1",
                    "measurement_address": "Addr",
                },
            },
        },
    )

    async def fake_upsert_state(*_args, **_kwargs):
        return None

    async def fake_upsert_draft(*_args, **_kwargs):
        return {"request_id": "draft-1", "collected_params": {}}

    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)

    result = await actions_applier.apply_actions(actions, 10, None, None, object(), object(), settings)

    assert result["measurement"]["id"] == 1
    assert any(c[0] == "schedule" for c in calls)
    assert any(c[0] == "msg" for c in calls)  # manager was notified


@pytest.mark.asyncio
async def test_apply_actions_schedule_measurement_links_existing_rendered_order(monkeypatch):
    calls = []
    from datetime import datetime
    from zoneinfo import ZoneInfo

    async def fake_schedule_measurement(**kwargs):
        calls.append(("schedule", kwargs))
        return {
            "id": 9,
            "client_chat_id": 10,
            "scheduled_time": datetime(2026, 4, 23, 11, 0, tzinfo=ZoneInfo("Asia/Bishkek")),
            "address": "Addr",
            "client_name": "Анна",
            "client_phone": "+1",
            "status": "scheduled",
            "order_request_id": kwargs.get("order_request_id"),
        }

    async def fake_get_rendered_draft(_pool, chat_id):
        assert chat_id == 10
        return {
            "request_id": "draft-1",
            "chat_id": 10,
            "status": "rendered",
            "rendered_order_id": "order-1",
            "order_status": "new",
            "details_json": {
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
            },
            "render_paths": {"0deg": "/tmp/a.png"},
            "price": {"total_price": 100, "currency": "USD"},
            "collected_params": {"shape": "Прямая"},
        }

    async def fake_update_client(*_args, **_kwargs):
        return None

    async def fake_send_message(token, chat_id, text, reply_markup=None):
        calls.append(("msg", chat_id, text))
        return {"ok": True}

    async def fake_upsert_state(*_args, **_kwargs):
        return None

    async def fake_upsert_draft(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(actions_applier, "schedule_measurement", fake_schedule_measurement)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)
    monkeypatch.setattr(actions_applier.postgres, "update_client", fake_update_client)
    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)
    monkeypatch.setattr(actions_applier.telegram_sender, "send_message", fake_send_message)

    settings = SimpleNamespace(manager_chat_ids_list=[99], manager_bot_token="manager", timezone="Asia/Bishkek")
    actions = ActionsJson(
        reply_text="ok",
        actions={
            "schedule_measurement": {
                "date": "2026-04-23",
                "time": "11:00",
                "client_name": "Анна",
                "phone": "+1",
                "address": "Addr",
            },
            "state_patch": {
                "mode": "scheduling",
                "step": "measurement_ready",
                "collected_params": {
                    "measurement_date": "2026-04-23",
                    "measurement_time": "11:00",
                    "measurement_name": "Анна",
                    "measurement_phone": "+1",
                    "measurement_address": "Addr",
                },
            },
        },
    )

    result = await actions_applier.apply_actions(
        actions,
        10,
        None,
        {"mode": "scheduling", "collected_params": {}},
        object(),
        object(),
        settings,
    )

    schedule_call = next(call for call in calls if call[0] == "schedule")
    assert schedule_call[1]["order_request_id"] == "order-1"
    assert result["measurement"]["order_request_id"] == "order-1"
    assert any(call[0] == "msg" and "Заказ: <code>order-1</code>" in call[2] for call in calls)


@pytest.mark.asyncio
async def test_apply_actions_suppresses_render_during_measurement_flow(monkeypatch):
    calls = []
    from datetime import datetime
    from zoneinfo import ZoneInfo

    async def fake_render_partition(*_args, **_kwargs):
        calls.append("render")
        return {"render_paths": {"0deg": "/tmp/a.png"}}

    async def fake_create_order(*_args, **_kwargs):
        calls.append("order")
        return {"request_id": "order-1"}

    async def fake_schedule_measurement(**kwargs):
        calls.append(("schedule", kwargs))
        return {
            "id": 5,
            "client_chat_id": 10,
            "scheduled_time": datetime(2026, 4, 23, 11, 0, tzinfo=ZoneInfo("Asia/Bishkek")),
            "address": "Addr",
            "client_name": "Анна",
            "client_phone": "+1",
            "status": "scheduled",
        }

    async def fake_update_client(_pool, chat_id, **fields):
        calls.append(("client", chat_id, fields))

    async def fake_send_message(*_args, **_kwargs):
        calls.append("manager_msg")
        return {"ok": True}

    async def fake_upsert_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))

    async def fake_upsert_draft(_pool, chat_id, collected_params, status="collecting", request_id=None):
        calls.append(("draft", chat_id, collected_params, status, request_id))
        return {"request_id": request_id or "draft-1", "collected_params": collected_params}

    async def fake_get_rendered_draft(_pool, chat_id):
        assert chat_id == 10
        return None

    monkeypatch.setattr(actions_applier, "render_partition", fake_render_partition)
    monkeypatch.setattr(actions_applier.postgres, "create_order", fake_create_order)
    monkeypatch.setattr(actions_applier, "schedule_measurement", fake_schedule_measurement)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)
    monkeypatch.setattr(actions_applier.postgres, "update_client", fake_update_client)
    monkeypatch.setattr(actions_applier.postgres, "upsert_conversation_state", fake_upsert_state)
    monkeypatch.setattr(actions_applier.postgres, "upsert_order_draft", fake_upsert_draft)
    monkeypatch.setattr(actions_applier.telegram_sender, "send_message", fake_send_message)

    settings = SimpleNamespace(
        manager_chat_ids_list=[99],
        manager_bot_token="manager",
        timezone="Asia/Bishkek",
    )
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
            },
            "schedule_measurement": {
                "date": "2026-04-23",
                "time": "11:00",
                "client_name": "Анна",
                "phone": "+1",
                "address": "Addr",
            },
            "state_patch": {
                "mode": "scheduling",
                "step": "collecting_contact_info",
                "collected_params": {
                    "measurement_date": "2026-04-23",
                    "measurement_time": "11:00",
                    "measurement_name": "Анна",
                    "measurement_phone": "+1",
                    "measurement_address": "Addr",
                },
            },
        },
    )

    result = await actions_applier.apply_actions(
        actions,
        10,
        None,
        {"mode": "rendering", "collected_params": {"shape": "Прямая"}},
        object(),
        object(),
        settings,
    )

    assert result["measurement"]["id"] == 5
    assert result["order"] is None
    assert "render" not in calls
    assert "order" not in calls
    assert ("state", 10, "scheduling", "measurement_scheduled", {"shape": "Прямая"}) in calls


@pytest.mark.asyncio
async def test_apply_actions_blocks_measurement_without_explicit_schedule_state(monkeypatch):
    async def fake_update_client(*_args, **_kwargs):
        return None

    async def fake_get_rendered_draft(*_args, **_kwargs):
        return None

    monkeypatch.setattr(actions_applier.postgres, "update_client", fake_update_client)
    monkeypatch.setattr(actions_applier.postgres, "get_rendered_order_draft", fake_get_rendered_draft)

    settings = SimpleNamespace(manager_chat_ids_list=[99], manager_bot_token="manager", timezone="Asia/Bishkek")
    actions = ActionsJson(
        reply_text="ok",
        actions={
            "schedule_measurement": {
                "date": "2026-04-23",
                "time": "11:00",
                "client_name": "Анна",
                "phone": "+1",
                "address": "Addr",
            },
            "state_patch": {"mode": "scheduling", "step": "collecting_contact_info", "collected_params": {}},
        },
    )

    with pytest.raises(ValueError, match="нужно уточнить"):
        await actions_applier.apply_actions(
            actions,
            10,
            None,
            {"mode": "scheduling", "collected_params": {"shape": "Прямая"}},
            object(),
            object(),
            settings,
        )


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

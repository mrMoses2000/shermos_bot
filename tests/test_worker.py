import pytest

from src.models import Job
from src.queue import worker


class FakeSender:
    def __init__(self):
        self.messages = []

    async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None):
        self.messages.append((token, chat_id, text, reply_markup))
        return len(self.messages)

    async def send_chat_action(self, *_args, **_kwargs):
        return {"ok": True}


@pytest.mark.asyncio
async def test_handle_clear_command(monkeypatch):
    calls = []

    async def clear_chat_messages(_pool, chat_id):
        calls.append(("clear", chat_id))

    async def upsert_conversation_state(_pool, chat_id, mode, step, collected_params):
        calls.append(("state", chat_id, mode, step, collected_params))

    async def insert_outbound_event(*_args, **_kwargs):
        return 42

    async def mark_outbound_sent(_pool, event_id, telegram_message_id=None):
        calls.append(("sent", event_id, telegram_message_id))

    monkeypatch.setattr(worker.postgres, "clear_chat_messages", clear_chat_messages)
    monkeypatch.setattr(worker.postgres, "upsert_conversation_state", upsert_conversation_state)
    monkeypatch.setattr(worker.postgres, "insert_outbound_event", insert_outbound_event)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", mark_outbound_sent)
    sender = FakeSender()
    job = Job(update_id=1, chat_id=100, user_id=100, text="/clear", msg_type="command")

    handled = await worker._handle_client_command(job, object(), sender)

    assert handled is True
    assert ("clear", 100) in calls
    assert sender.messages[0][2] == "История диалога очищена."


@pytest.mark.asyncio
async def test_send_render_result_includes_detailed_price_caption():
    from tests.helpers import FakeSender as RenderSender

    sender = RenderSender()
    job = Job(update_id=1, chat_id=100, user_id=100, text="рендер")
    result = {
        "render_paths": {"0deg": "/tmp/render.png"},
        "order": {"request_id": "order-9"},
        "price": {
            "total_price": 1203.2,
            "currency": "USD",
            "details": {
                "area_sq_m": 6,
                "partition_type": "sliding_2",
                "base_rate_per_sqm": 170,
                "base_price": 1020,
                "matting": "matting_solid",
                "matting_price": 42,
                "complex_pattern_price": 18,
                "frame_surcharge": 43.2,
                "volume_discount": 0,
                "handle_price": 80,
                "rows": 1,
                "cols": 2,
            },
        },
    }

    await worker._send_render_result(job, object(), sender, result)

    caption = sender.photos[0][3]
    assert "Тип:" in caption
    assert "Раздвижная 2 створки" in caption
    assert "Площадь:" in caption
    assert "Базовая ставка:" in caption
    assert "Сплошная матировка: +42 $" in caption
    assert "Итого:" in caption

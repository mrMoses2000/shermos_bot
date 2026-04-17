import pytest
from src.queue.worker import _handle_client_callback, _send_gallery_works, _send_render_result
from src.models import Job
from tests.helpers import FakeSender, FakePool

@pytest.mark.asyncio
async def test_gallery_show_2_works(monkeypatch, tmp_path):
    from src.config import settings
    monkeypatch.setattr(settings, "gallery_dir", str(tmp_path))
    
    sender = FakeSender()
    pool = FakePool()
    job = Job(update_id=1, chat_id=123, user_id=123, msg_type="callback_query", callback_data="gallery_show:ord1:fixed", bot_type="client", text="", raw_update={})
    
    async def fake_pick(*args, **kwargs):
        return [
            {"id": "w1", "title": "Work 1", "photos": [{"file_path": "w1/1.png"}, {"file_path": "w1/2.png"}]},
            {"id": "w2", "title": "Work 2", "photos": [{"file_path": "w2/1.png"}]}
        ]
    monkeypatch.setattr("src.queue.worker.postgres.pick_random_gallery_works", fake_pick)
    
    handled = await _handle_client_callback(job, pool, sender)
    assert handled is True
    
    assert len(sender.messages) == 1
    assert len(sender.media_groups) == 1
    assert len(sender.photos) == 1
    # First is media_group for w1
    assert len(sender.media_groups[0][2]) == 2
    assert sender.photos[0][2].endswith("w2/1.png")
    assert "Оцените, пожалуйста" in sender.messages[0]["text"]

@pytest.mark.asyncio
async def test_gallery_show_zero_works(monkeypatch):
    sender = FakeSender()
    pool = FakePool()
    job = Job(update_id=1, chat_id=123, user_id=123, msg_type="callback_query", callback_data="gallery_show:ord1:fixed", bot_type="client", text="", raw_update={})
    
    async def fake_pick(*args, **kwargs):
        return []
    monkeypatch.setattr("src.queue.worker.postgres.pick_random_gallery_works", fake_pick)
    
    await _handle_client_callback(job, pool, sender)
    
    assert len(sender.messages) == 2
    assert "Скоро пополним базу" in sender.messages[0]["text"]
    assert "Оцените, пожалуйста" in sender.messages[1]["text"]

@pytest.mark.asyncio
async def test_gallery_skip(monkeypatch):
    sender = FakeSender()
    pool = FakePool()
    job = Job(update_id=1, chat_id=123, user_id=123, msg_type="callback_query", callback_data="gallery_skip:ord1:fixed", bot_type="client", text="", raw_update={})
    
    handled = await _handle_client_callback(job, pool, sender)
    assert handled is True
    
    assert len(sender.messages) == 1
    assert "Оцените, пожалуйста" in sender.messages[0]["text"]

@pytest.mark.asyncio
async def test_unknown_callback():
    sender = FakeSender()
    pool = FakePool()
    job = Job(update_id=1, chat_id=123, user_id=123, msg_type="callback_query", callback_data="unknown:ord1", bot_type="client", text="", raw_update={})
    handled = await _handle_client_callback(job, pool, sender)
    assert handled is False

@pytest.mark.asyncio
async def test_send_render_result_sends_offer_keyboard():
    sender = FakeSender()
    pool = FakePool()
    job = Job(update_id=1, chat_id=123, user_id=123, msg_type="command", bot_type="client", text="", raw_update={})
    
    action_result = {
        "render_paths": {"v1": "path/1.jpg"},
        "order": {"request_id": "ord1"},
        "price": {"details": {"partition_type": "fixed"}}
    }
    await _send_render_result(job, pool, sender, action_result)
    
    assert len(sender.photos) == 1
    assert len(sender.messages) == 1
    assert "Показать 3 реальные работы" in sender.messages[0]["text"]
    assert "gallery_show:ord1:fixed" in str(sender.messages[0]["reply_markup"])
"""Tests for voice transcription flow in the worker pipeline."""

from __future__ import annotations

import pytest

from src.config import settings
from src.models import Job
from src.queue import worker


class VoiceFakeSender:
    def __init__(self, file_path="voice/file_1.oga", audio_bytes=b"raw-oga-bytes"):
        self.messages = []
        self.actions = []
        self.downloaded = []
        self.get_file_calls = []
        self.file_path = file_path
        self.audio_bytes = audio_bytes

    async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None):
        self.messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return len(self.messages)

    async def send_chat_action(self, token, chat_id, action="typing"):
        self.actions.append((chat_id, action))
        return {"ok": True}

    async def get_file(self, token, file_id):
        self.get_file_calls.append(file_id)
        return {"file_path": self.file_path, "file_size": 1000}

    async def download_file(self, token, file_path):
        self.downloaded.append(file_path)
        return self.audio_bytes


def _voice_job(chat_id: int = 42, file_id: str = "voice-id") -> Job:
    return Job(
        update_id=1,
        chat_id=chat_id,
        user_id=chat_id,
        text="",
        msg_type="voice",
        raw_update={
            "message": {
                "chat": {"id": chat_id},
                "from": {"id": chat_id, "first_name": "Ivan"},
                "voice": {"file_id": file_id, "duration": 3},
            }
        },
    )


def _patch_outbound_recording(monkeypatch):
    async def insert_outbound_event(*_a, **_kw):
        return 1

    async def mark_outbound_sent(*_a, **_kw):
        return None

    async def mark_update_status(*_a, **_kw):
        return None

    monkeypatch.setattr(worker.postgres, "insert_outbound_event", insert_outbound_event)
    monkeypatch.setattr(worker.postgres, "mark_outbound_sent", mark_outbound_sent)
    monkeypatch.setattr(worker.postgres, "mark_update_status", mark_update_status)


@pytest.mark.asyncio
async def test_resolve_voice_text_rejects_when_no_file_id(monkeypatch):
    _patch_outbound_recording(monkeypatch)
    monkeypatch.setattr(settings, "assemblyai_api_key", "secret")
    sender = VoiceFakeSender()
    job = Job(
        update_id=1, chat_id=1, user_id=1, msg_type="voice",
        raw_update={"message": {"chat": {"id": 1}}},
    )

    ok = await worker._resolve_voice_text(job, object(), sender)
    assert ok is False
    assert "Отправьте, пожалуйста, текстом" in sender.messages[0]["text"]


@pytest.mark.asyncio
async def test_resolve_voice_text_rejects_when_key_missing(monkeypatch):
    _patch_outbound_recording(monkeypatch)
    monkeypatch.setattr(settings, "assemblyai_api_key", "")
    sender = VoiceFakeSender()
    job = _voice_job()

    ok = await worker._resolve_voice_text(job, object(), sender)
    assert ok is False
    assert "пока недоступно" in sender.messages[0]["text"]


@pytest.mark.asyncio
async def test_resolve_voice_text_happy_path(monkeypatch):
    _patch_outbound_recording(monkeypatch)
    monkeypatch.setattr(settings, "assemblyai_api_key", "secret")
    sender = VoiceFakeSender(audio_bytes=b"opus-bytes")

    async def fake_transcribe(audio, language=None):
        assert audio == b"opus-bytes"
        return "прямая перегородка три на два шестьдесят"

    monkeypatch.setattr(worker, "transcribe_voice", fake_transcribe)

    job = _voice_job(chat_id=77, file_id="v-77")
    ok = await worker._resolve_voice_text(job, object(), sender)

    assert ok is True
    assert job.text == "прямая перегородка три на два шестьдесят"
    assert job.msg_type == "text"
    assert ("record_voice",) == (sender.actions[0][1],)
    assert sender.get_file_calls == ["v-77"]
    assert sender.downloaded == ["voice/file_1.oga"]
    # Transcript echo message to client for verification
    assert any("Распознано" in m["text"] for m in sender.messages)


@pytest.mark.asyncio
async def test_resolve_voice_text_handles_transcription_error(monkeypatch):
    _patch_outbound_recording(monkeypatch)
    monkeypatch.setattr(settings, "assemblyai_api_key", "secret")
    sender = VoiceFakeSender()

    async def failing_transcribe(audio, language=None):
        raise worker.TranscriptionError("AssemblyAI down")

    monkeypatch.setattr(worker, "transcribe_voice", failing_transcribe)

    job = _voice_job()
    ok = await worker._resolve_voice_text(job, object(), sender)
    assert ok is False
    assert any("Не удалось распознать" in m["text"] for m in sender.messages)


@pytest.mark.asyncio
async def test_resolve_voice_text_handles_download_error(monkeypatch):
    _patch_outbound_recording(monkeypatch)
    monkeypatch.setattr(settings, "assemblyai_api_key", "secret")

    class BrokenSender(VoiceFakeSender):
        async def download_file(self, token, file_path):
            raise RuntimeError("Telegram CDN down")

    sender = BrokenSender()
    job = _voice_job()

    ok = await worker._resolve_voice_text(job, object(), sender)
    assert ok is False
    assert any("Не удалось получить" in m["text"] for m in sender.messages)


@pytest.mark.asyncio
async def test_resolve_voice_text_rejects_empty_transcript(monkeypatch):
    _patch_outbound_recording(monkeypatch)
    monkeypatch.setattr(settings, "assemblyai_api_key", "secret")
    sender = VoiceFakeSender()

    async def empty(audio, language=None):
        return ""

    monkeypatch.setattr(worker, "transcribe_voice", empty)

    job = _voice_job()
    ok = await worker._resolve_voice_text(job, object(), sender)
    assert ok is False
    assert any("не распознано" in m["text"].lower() for m in sender.messages)


@pytest.mark.asyncio
async def test_process_client_job_transcribes_voice_then_runs_llm(monkeypatch):
    """End-to-end: voice message should be transcribed and fed into the LLM path."""
    _patch_outbound_recording(monkeypatch)
    monkeypatch.setattr(settings, "assemblyai_api_key", "secret")

    # Transcribe → known text
    async def fake_transcribe(audio, language=None):
        return "рассчитай перегородку три на два шестьдесят"

    monkeypatch.setattr(worker, "transcribe_voice", fake_transcribe)

    # Skip all DB lookups the LLM path does
    async def _noop(*_a, **_kw):
        return None

    async def _ret(*_a, **_kw):
        return {}

    async def get_client_by_chat_id(*_a, **_kw):
        return {"id": 1, "chat_id": 77}

    async def create_client(*_a, **_kw):
        return {"id": 1, "chat_id": 77}

    async def get_conversation_state(*_a, **_kw):
        return None

    async def get_chat_messages(*_a, **_kw):
        return []

    async def insert_chat_message(*_a, **_kw):
        return None

    monkeypatch.setattr(worker.postgres, "get_client_by_chat_id", get_client_by_chat_id)
    monkeypatch.setattr(worker.postgres, "create_client", create_client)
    monkeypatch.setattr(worker.postgres, "get_conversation_state", get_conversation_state)
    monkeypatch.setattr(worker.postgres, "get_chat_messages", get_chat_messages)
    monkeypatch.setattr(worker.postgres, "insert_chat_message", insert_chat_message)

    async def load_slots(*_a, **_kw):
        return {}

    monkeypatch.setattr(worker, "_load_available_slots", load_slots)

    captured = {}

    def fake_build_prompt(text, client, state, history, available_slots=None):
        captured["prompt_text"] = text
        return "PROMPT"

    monkeypatch.setattr(worker, "build_prompt", fake_build_prompt)

    async def fake_call_llm(prompt):
        return '{"reply_text": "Ок, считаю.", "actions": null}'

    monkeypatch.setattr(worker, "call_llm", fake_call_llm)

    def fake_parse_actions(raw):
        class Parsed:
            reply_text = "Ок, считаю."
            actions = None

        return Parsed()

    monkeypatch.setattr(worker, "parse_actions", fake_parse_actions)

    async def fake_apply_actions(*_a, **_kw):
        return {}

    monkeypatch.setattr(worker, "apply_actions", fake_apply_actions)

    class FakeRedis:
        async def acquire_user_lock(self, chat_id, ttl=180):
            return True

        async def release_user_lock(self, chat_id):
            return None

        async def enqueue_job(self, queue, job):
            return None

    sender = VoiceFakeSender()
    job = _voice_job(chat_id=77, file_id="v-abc")

    await worker.process_client_job(job, object(), FakeRedis(), sender)

    # The transcript landed in the prompt
    assert captured["prompt_text"] == "рассчитай перегородку три на два шестьдесят"
    # Both the transcript echo AND the LLM reply were sent
    texts = [m["text"] for m in sender.messages]
    assert any("Распознано" in t for t in texts)
    assert any("Ок, считаю" in t for t in texts)

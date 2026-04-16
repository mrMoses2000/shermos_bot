import asyncio

import pytest

from src.bot import transcribe
from src.bot.transcribe import (
    TranscriptionError,
    extract_voice_file_id,
    transcribe_voice,
)
from src.config import settings


def test_extract_voice_file_id_voice():
    update = {"message": {"voice": {"file_id": "abc123", "duration": 3}}}
    assert extract_voice_file_id(update) == "abc123"


def test_extract_voice_file_id_audio():
    update = {"message": {"audio": {"file_id": "audio-id", "mime_type": "audio/mpeg"}}}
    assert extract_voice_file_id(update) == "audio-id"


def test_extract_voice_file_id_edited_message():
    update = {"edited_message": {"voice": {"file_id": "edited-id"}}}
    assert extract_voice_file_id(update) == "edited-id"


def test_extract_voice_file_id_none_for_plain_text():
    update = {"message": {"text": "hello"}}
    assert extract_voice_file_id(update) is None


def test_extract_voice_file_id_none_for_empty_update():
    assert extract_voice_file_id({}) is None


@pytest.mark.asyncio
async def test_transcribe_voice_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "")
    with pytest.raises(TranscriptionError, match="ASSEMBLYAI_API_KEY"):
        await transcribe_voice(b"audio")


@pytest.mark.asyncio
async def test_transcribe_voice_raises_on_empty_bytes(monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "test-key")
    with pytest.raises(TranscriptionError, match="Empty audio"):
        await transcribe_voice(b"")


@pytest.mark.asyncio
async def test_transcribe_voice_happy_path(monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "test-key")
    monkeypatch.setattr(settings, "transcription_language", "ru")

    def fake_sync(audio, language):
        assert audio == b"raw-audio"
        assert language == "ru"
        return "  привет мир  "

    monkeypatch.setattr(transcribe, "_do_transcribe", fake_sync)

    result = await transcribe_voice(b"raw-audio")
    # The blocking helper trims inside _do_transcribe; async wrapper just returns.
    assert result.strip() == "привет мир"


@pytest.mark.asyncio
async def test_transcribe_voice_explicit_language_override(monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "test-key")
    captured = {}

    def fake_sync(audio, language):
        captured["language"] = language
        return "hello"

    monkeypatch.setattr(transcribe, "_do_transcribe", fake_sync)
    await transcribe_voice(b"audio", language="en")
    assert captured["language"] == "en"


@pytest.mark.asyncio
async def test_transcribe_voice_wraps_timeouts(monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "test-key")
    monkeypatch.setattr(settings, "transcription_timeout_seconds", 1)

    def slow(audio, language):
        import time
        time.sleep(2)
        return "never"

    monkeypatch.setattr(transcribe, "_do_transcribe", slow)

    with pytest.raises(TranscriptionError, match="timed out"):
        await transcribe_voice(b"audio")


@pytest.mark.asyncio
async def test_transcribe_voice_wraps_generic_errors(monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "test-key")

    def boom(audio, language):
        raise ValueError("network exploded")

    monkeypatch.setattr(transcribe, "_do_transcribe", boom)

    with pytest.raises(TranscriptionError, match="network exploded"):
        await transcribe_voice(b"audio")


@pytest.mark.asyncio
async def test_transcribe_voice_propagates_transcription_error(monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "test-key")

    def typed_error(audio, language):
        raise TranscriptionError("AssemblyAI error: invalid audio")

    monkeypatch.setattr(transcribe, "_do_transcribe", typed_error)

    with pytest.raises(TranscriptionError, match="invalid audio"):
        await transcribe_voice(b"audio")

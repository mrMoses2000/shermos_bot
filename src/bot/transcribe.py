"""AssemblyAI voice transcription for Telegram voice/audio messages.

The assemblyai SDK is synchronous; we wrap it with asyncio.to_thread so the
worker event loop stays responsive while waiting for the transcript.

Telegram voice messages are delivered as OGG/Opus (.oga); AssemblyAI accepts
that format directly, so no ffmpeg conversion is needed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class TranscriptionError(RuntimeError):
    """Raised when transcription cannot be completed."""


def _do_transcribe(audio_bytes: bytes, language: str) -> str:
    """Blocking transcription call. Must run in a worker thread."""
    # Import lazily so the module can be loaded (and tests can monkeypatch
    # `transcribe_voice`) even if the `assemblyai` package is absent.
    import assemblyai as aai

    aai.settings.api_key = settings.assemblyai_api_key

    # AssemblyAI rejects the default "speech_models: []" and expects an explicit
    # list. The SDK's SpeechModel enum lags behind server-side names; the `speech_models`
    # (plural) free-form list is the forward-compatible channel.
    speech_models = ["universal-2"]

    if language == "auto":
        config = aai.TranscriptionConfig(
            language_detection=True,
            punctuate=True,
            format_text=True,
            speech_models=speech_models,
        )
    else:
        config = aai.TranscriptionConfig(
            language_code=language,
            punctuate=True,
            format_text=True,
            speech_models=speech_models,
        )

    transcriber = aai.Transcriber(config=config)
    transcript = transcriber.transcribe(audio_bytes)

    if transcript.status == aai.TranscriptStatus.error:
        raise TranscriptionError(transcript.error or "AssemblyAI returned error status")

    text = (transcript.text or "").strip()
    return text


async def transcribe_voice(audio_bytes: bytes, language: str | None = None) -> str:
    """Transcribe raw voice bytes to text using AssemblyAI.

    Args:
        audio_bytes: Raw bytes downloaded from Telegram's CDN (OGG/Opus).
        language: ISO language code ("ru", "en", …) or "auto". Defaults to
            settings.transcription_language.

    Returns:
        Transcribed text, trimmed. Empty string if the audio was silent.

    Raises:
        TranscriptionError: On AssemblyAI failure, timeout, or missing key.
    """
    if not settings.assemblyai_api_key:
        raise TranscriptionError("ASSEMBLYAI_API_KEY is not configured")
    if not audio_bytes:
        raise TranscriptionError("Empty audio payload")

    lang = language or settings.transcription_language
    timeout = settings.transcription_timeout_seconds

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_transcribe, audio_bytes, lang),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise TranscriptionError(f"Transcription timed out after {timeout}s") from exc
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(str(exc)) from exc


def extract_voice_file_id(raw_update: dict[str, Any]) -> str | None:
    """Pull the file_id from a Telegram update carrying a voice/audio message."""
    message = raw_update.get("message") or raw_update.get("edited_message") or {}
    voice = message.get("voice") or {}
    audio = message.get("audio") or {}
    file_id = voice.get("file_id") or audio.get("file_id")
    return file_id if isinstance(file_id, str) and file_id else None

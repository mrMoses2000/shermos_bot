"""Compact deterministic conversation memory for prompt context."""

from __future__ import annotations

import re
from typing import Any

from src.config import settings
from src.db import postgres
from src.utils.json_tools import ensure_json_object
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

SUMMARY_TRIGGER_MESSAGES = 8
KEEP_RECENT_MESSAGES = 4
MAX_SUMMARY_CHARS: int = settings.memory_summary_max_chars
MAX_NOTE_CHARS = 220
MAX_UNSUMMARIZED_FETCH = 80

# Regex patterns to extract numeric dimension facts for preservation
_DIMENSION_PATTERNS = [
    (r"(?:ширин[аеу]|width)[^\d]*(\d+(?:[.,]\d+)?)", "width"),
    (r"(?:высот[аеу]|height)[^\d]*(\d+(?:[.,]\d+)?)", "height"),
    (r"(?:глубин[аеу]|depth)[^\d]*(\d+(?:[.,]\d+)?)", "depth"),
    (r"(?:размер)[^\d]*(\d+(?:[.,]\d+)?)", "size"),
]

_LLM_COMPRESSION_PROMPT = (
    "Сожми этот контекст разговора, СОХРАНИВ все размеры (высота, ширина, глубина), "
    "тип стекла, цвет профиля, контактные данные клиента. "
    "Лимит {limit} символов. Текст:\n{text}"
)

_FACT_KEYS = (
    "shape",
    "shape_side",
    "height",
    "width_a",
    "width_b",
    "width_c",
    "partition_type",
    "glass_type",
    "frame_color",
    "matting",
    "add_handle",
    "handle_wall",
    "handle_sections",
    "door_wall",
    "door_section",
    "rows",
    "cols",
    "rows_front",
    "cols_front",
    "rows_side",
    "cols_side",
    "rows_left",
    "cols_left",
    "rows_right",
    "cols_right",
    "_rendered_order_id",
    "measurement_date",
    "measurement_time",
    "measurement_name",
    "measurement_phone",
    "measurement_address",
)


def _compact_text(value: Any, limit: int = MAX_NOTE_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def build_memory_facts(
    client: dict[str, Any] | None,
    state: dict[str, Any] | None,
    rendered_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collected = ensure_json_object((state or {}).get("collected_params", {}))
    facts = {
        key: collected[key]
        for key in _FACT_KEYS
        if key in collected and collected[key] not in (None, "", [])
    }
    if state:
        facts["mode"] = state.get("mode")
        facts["step"] = state.get("step")
    if client:
        profile = {
            key: client.get(key)
            for key in ("name", "phone", "address")
            if client.get(key)
        }
        if profile:
            facts["client_profile"] = profile
    if rendered_draft:
        request_id = rendered_draft.get("rendered_order_id") or rendered_draft.get("request_id")
        if request_id:
            facts["current_order_request_id"] = request_id
            facts["_rendered_order_id"] = request_id
        if rendered_draft.get("order_status"):
            facts["current_order_status"] = rendered_draft.get("order_status")
    return facts


def _extract_dimension_facts(text: str) -> dict[str, str]:
    """Extract numeric dimension mentions from text for preservation in structured form."""
    found: dict[str, str] = {}
    for pattern, key in _DIMENSION_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            found[key] = m.group(1).replace(",", ".")
    return found


def _build_fact_prefix(facts: dict[str, str]) -> str:
    """Turn extracted facts dict into a short prefix string."""
    if not facts:
        return ""
    parts = [f"{k}={v}" for k, v in facts.items()]
    return "[facts: " + ", ".join(parts) + "] "


def merge_memory_summary(
    existing_summary: str,
    messages_to_summarize: list[dict[str, Any]],
) -> tuple[str, int]:
    """Build a new summary by appending *messages_to_summarize* to *existing_summary*.

    If the result exceeds MAX_SUMMARY_CHARS, byte-truncation is used as the
    synchronous fallback (the caller may upgrade to LLM compression via
    ``merge_memory_summary_async``).
    """
    if not messages_to_summarize:
        return existing_summary or "", 0

    notes: list[str] = []
    for message in messages_to_summarize:
        role = "Клиент" if message.get("role") == "user" else "Ассистент"
        text = _compact_text(message.get("text"))
        if text:
            notes.append(f"{role}: {text}")

    parts = [part for part in [(existing_summary or "").strip(), *notes] if part]
    summary = "\n".join(parts)
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = "[older context truncated] " + summary[-MAX_SUMMARY_CHARS:].lstrip()
    last_id = int(messages_to_summarize[-1]["id"])
    return summary, last_id


async def merge_memory_summary_async(
    existing_summary: str,
    messages_to_summarize: list[dict[str, Any]],
    call_llm_fn=None,
) -> tuple[str, int]:
    """Async version of merge_memory_summary with LLM compression.

    Steps:
    1. Concatenate existing summary + new messages.
    2. If under MAX_SUMMARY_CHARS, return as-is.
    3. Extract numeric dimension facts from the *full* text before truncation.
    4. Attempt LLM compression that preserves key facts.
    5. On LLM failure, fall back to byte-truncation with a prefix marker.
    """
    if not messages_to_summarize:
        return existing_summary or "", 0

    notes: list[str] = []
    for message in messages_to_summarize:
        role = "Клиент" if message.get("role") == "user" else "Ассистент"
        text = _compact_text(message.get("text"))
        if text:
            notes.append(f"{role}: {text}")

    parts = [part for part in [(existing_summary or "").strip(), *notes] if part]
    full_summary = "\n".join(parts)
    last_id = int(messages_to_summarize[-1]["id"])

    if len(full_summary) <= MAX_SUMMARY_CHARS:
        return full_summary, last_id

    # Extract numeric facts from the full text before any truncation
    extracted_facts = _extract_dimension_facts(full_summary)

    # Attempt LLM compression
    if call_llm_fn is not None:
        try:
            prompt = _LLM_COMPRESSION_PROMPT.format(
                limit=MAX_SUMMARY_CHARS - 20,
                text=full_summary,
            )
            compressed = await call_llm_fn(prompt)
            # Strip any JSON wrapper if the LLM returns structured output
            compressed = compressed.strip()
            if compressed.startswith("{"):
                import json as _json
                try:
                    obj = _json.loads(compressed)
                    compressed = obj.get("reply_text") or obj.get("summary") or compressed
                except Exception:
                    pass
            if compressed and len(compressed) <= MAX_SUMMARY_CHARS:
                return compressed, last_id
        except Exception as exc:
            logger.warning("memory_llm_compression_failed", extra={"error": str(exc)})

    # Fallback: byte-truncate, but prepend any extracted facts so they survive
    fact_prefix = _build_fact_prefix(extracted_facts)
    available = MAX_SUMMARY_CHARS - len(fact_prefix)
    truncated = full_summary[-available:].lstrip() if available > 0 else ""
    return fact_prefix + "[older context truncated] " + truncated, last_id


async def refresh_conversation_memory_if_needed(pg_pool, chat_id: int) -> dict[str, Any] | None:
    from src.llm.executor import call_llm as _call_llm  # local import to avoid circular dep

    memory = await postgres.get_conversation_memory(pg_pool, chat_id)
    summarized_until = int((memory or {}).get("summarized_until_message_id") or 0)
    messages = await postgres.get_chat_messages_after(
        pg_pool,
        chat_id,
        after_message_id=summarized_until,
        limit=MAX_UNSUMMARIZED_FETCH,
    )

    client = await postgres.get_client_by_chat_id(pg_pool, chat_id)
    state = await postgres.get_conversation_state(pg_pool, chat_id)
    rendered_draft = await postgres.get_rendered_order_draft(pg_pool, chat_id)
    facts = build_memory_facts(client, state, rendered_draft)

    summary_text = (memory or {}).get("summary_text") or ""
    if len(summary_text) > MAX_SUMMARY_CHARS:
        summary_text = summary_text[-MAX_SUMMARY_CHARS:].lstrip()
    new_summarized_until = summarized_until
    should_summarize = len(messages) > SUMMARY_TRIGGER_MESSAGES
    if should_summarize:
        to_summarize = messages[:-KEEP_RECENT_MESSAGES]
        summary_text, new_summarized_until = await merge_memory_summary_async(
            summary_text, to_summarize, call_llm_fn=_call_llm
        )

    summary_was_compacted = bool(memory) and summary_text != ((memory or {}).get("summary_text") or "")
    if (
        not memory
        or should_summarize
        or summary_was_compacted
        or facts != ensure_json_object(memory.get("facts_json", {}))
    ):
        updated = await postgres.upsert_conversation_memory(
            pg_pool,
            chat_id,
            summary_text,
            facts,
            new_summarized_until,
        )
        logger.info(
            "conversation_memory_refreshed",
            extra={
                "chat_id": chat_id,
                "summarized_messages": max(0, len(messages) - KEEP_RECENT_MESSAGES)
                if should_summarize
                else 0,
                "summarized_until_message_id": updated.get("summarized_until_message_id"),
            },
        )
        return updated
    return memory

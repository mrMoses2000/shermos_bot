"""Compact deterministic conversation memory for prompt context."""

from __future__ import annotations

from typing import Any

from src.db import postgres
from src.utils.json_tools import ensure_json_object
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

SUMMARY_TRIGGER_MESSAGES = 8
KEEP_RECENT_MESSAGES = 4
MAX_SUMMARY_CHARS = 900
MAX_NOTE_CHARS = 220
MAX_UNSUMMARIZED_FETCH = 80

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


def merge_memory_summary(
    existing_summary: str,
    messages_to_summarize: list[dict[str, Any]],
) -> tuple[str, int]:
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
        summary = summary[-MAX_SUMMARY_CHARS:].lstrip()
    last_id = int(messages_to_summarize[-1]["id"])
    return summary, last_id


async def refresh_conversation_memory_if_needed(pg_pool, chat_id: int) -> dict[str, Any] | None:
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
        summary_text, new_summarized_until = merge_memory_summary(summary_text, to_summarize)

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

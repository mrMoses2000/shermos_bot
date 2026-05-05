import pytest

from src.llm import conversation_memory
from src.llm.conversation_memory import merge_memory_summary_async


def test_build_memory_facts_prefers_structured_state_and_order():
    facts = conversation_memory.build_memory_facts(
        {"name": "Моисей", "phone": "+7700", "address": "Адрес"},
        {
            "mode": "collecting",
            "step": "materials",
            "collected_params": {
                "shape": "Г-образная",
                "height": 1.8,
                "glass_type": "3",
                "frame_color": "2",
                "ignored": "value",
            },
        },
        {"request_id": "req-1", "order_status": "new"},
    )

    assert facts["shape"] == "Г-образная"
    assert facts["height"] == 1.8
    assert facts["glass_type"] == "3"
    assert facts["frame_color"] == "2"
    assert facts["mode"] == "collecting"
    assert facts["client_profile"]["name"] == "Моисей"
    assert facts["current_order_request_id"] == "req-1"
    assert "ignored" not in facts


def test_merge_memory_summary_compacts_messages_and_advances_cursor():
    messages = [
        {"id": 10, "role": "user", "text": "x" * 400},
        {"id": 11, "role": "assistant", "text": "ответ"},
    ]

    summary, last_id = conversation_memory.merge_memory_summary("старое", messages)

    assert "старое" in summary
    assert "Клиент: " in summary
    assert "x" * 300 not in summary
    assert "Ассистент: ответ" in summary
    assert last_id == 11


@pytest.mark.asyncio
async def test_refresh_conversation_memory_summarizes_old_messages(monkeypatch):
    calls = []
    memory = {"summary_text": "", "facts_json": {}, "summarized_until_message_id": 0}
    messages = [
        {"id": idx, "role": "user" if idx % 2 else "assistant", "text": f"message {idx}"}
        for idx in range(1, 11)
    ]

    async def fake_get_memory(_pool, chat_id):
        return memory

    async def fake_get_after(_pool, chat_id, after_message_id=0, limit=100):
        return messages

    async def fake_get_client(_pool, chat_id):
        return {"name": "Анна"}

    async def fake_get_state(_pool, chat_id):
        return {"mode": "collecting", "step": "shape", "collected_params": {"shape": "Прямая"}}

    async def fake_get_draft(_pool, chat_id):
        return None

    async def fake_upsert(_pool, chat_id, summary_text, facts_json, summarized_until_message_id):
        calls.append((chat_id, summary_text, facts_json, summarized_until_message_id))
        return {
            "chat_id": chat_id,
            "summary_text": summary_text,
            "facts_json": facts_json,
            "summarized_until_message_id": summarized_until_message_id,
        }

    monkeypatch.setattr(conversation_memory.postgres, "get_conversation_memory", fake_get_memory)
    monkeypatch.setattr(conversation_memory.postgres, "get_chat_messages_after", fake_get_after)
    monkeypatch.setattr(conversation_memory.postgres, "get_client_by_chat_id", fake_get_client)
    monkeypatch.setattr(conversation_memory.postgres, "get_conversation_state", fake_get_state)
    monkeypatch.setattr(conversation_memory.postgres, "get_rendered_order_draft", fake_get_draft)
    monkeypatch.setattr(conversation_memory.postgres, "upsert_conversation_memory", fake_upsert)

    updated = await conversation_memory.refresh_conversation_memory_if_needed(object(), 123)

    assert updated["summarized_until_message_id"] == 6
    assert calls[0][2]["shape"] == "Прямая"
    assert "message 1" in calls[0][1]
    assert "message 7" not in calls[0][1]


# ---------------------------------------------------------------------------
# merge_memory_summary_async — LLM compression tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merge_memory_summary_async_no_truncation_skips_llm():
    """Short summary under MAX_SUMMARY_CHARS: LLM must NOT be called."""
    llm_calls = []

    async def fake_llm(prompt):
        llm_calls.append(prompt)
        return "compressed"

    messages = [{"id": 1, "role": "user", "text": "hello"}]
    summary, last_id = await merge_memory_summary_async("short", messages, call_llm_fn=fake_llm)

    assert last_id == 1
    assert "short" in summary
    assert "hello" in summary
    assert llm_calls == [], "LLM must not be called when summary fits within limit"


@pytest.mark.asyncio
async def test_merge_memory_summary_uses_llm_when_oversized(monkeypatch):
    """When the summary exceeds MAX_SUMMARY_CHARS, LLM is called and its result used."""
    monkeypatch.setattr(conversation_memory, "MAX_SUMMARY_CHARS", 50)

    llm_calls = []
    LLM_RETURN = "краткий контекст: ширина 3.5, высота 2.7"

    async def fake_llm(prompt):
        llm_calls.append(prompt)
        return LLM_RETURN

    # Build messages that will exceed 50 chars when combined with existing summary
    messages = [{"id": 5, "role": "user", "text": "A" * 40}]
    existing = "B" * 20

    summary, last_id = await merge_memory_summary_async(existing, messages, call_llm_fn=fake_llm)

    assert last_id == 5
    assert len(llm_calls) == 1, "LLM must be called when summary is oversized"
    assert summary == LLM_RETURN, "Result should be the LLM's return value"


@pytest.mark.asyncio
async def test_merge_memory_summary_falls_back_on_llm_error(monkeypatch):
    """When LLM raises, byte-truncation fallback is used with [older context truncated] prefix."""
    monkeypatch.setattr(conversation_memory, "MAX_SUMMARY_CHARS", 50)

    async def failing_llm(prompt):
        raise RuntimeError("LLM unavailable")

    messages = [{"id": 7, "role": "user", "text": "D" * 40}]
    existing = "C" * 20

    summary, last_id = await merge_memory_summary_async(existing, messages, call_llm_fn=failing_llm)

    assert last_id == 7
    assert "[older context truncated]" in summary, (
        "Fallback truncation must include the [older context truncated] marker"
    )

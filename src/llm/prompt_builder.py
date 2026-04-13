"""Prompt assembler for Gemini CLI."""

from __future__ import annotations

import json
from typing import Any

from src.llm.tools_schema import get_tools_schema
from src.utils.config_manager import config


def _materials_section() -> str:
    glass = config.get_all_materials("glass_types")
    frames = config.get_all_materials("frame_colors")
    glass_lines = [f'{key}: {value.get("name", key)}' for key, value in glass.items()]
    frame_lines = [f'{key}: {value.get("name", key)}' for key, value in frames.items()]
    return (
        "Типы стекла:\n"
        + "\n".join(glass_lines)
        + "\n\nЦвета профиля:\n"
        + "\n".join(frame_lines)
    )


def build_prompt(
    user_message: str,
    client_profile: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    chat_messages: list[dict[str, Any]],
) -> str:
    profile_text = "Новый клиент"
    if client_profile:
        profile_text = json.dumps(client_profile, ensure_ascii=False, default=str)

    state = conversation_state or {"mode": "idle", "step": None, "collected_params": {}}
    history_lines = []
    for message in chat_messages:
        role = "Клиент" if message.get("role") == "user" else "Ассистент"
        history_lines.append(f"{role}: {message.get('text', '')}")

    return f"""
Ты эксперт-консультант компании Shermos по стеклянным перегородкам.
Всегда отвечай на русском языке. Формат Telegram HTML: используй только <b>, <i>, переносы строк.
Не используй markdown. Не выдумывай параметры.

Задача:
- Помочь клиенту выбрать стеклянную перегородку.
- Собрать все обязательные параметры перед рендером.
- Перед render_partition обязательно показать краткое резюме и спросить: "Рендерить?"
- Если клиент уже подтвердил рендер, можно вызвать render_partition.
- Если данных мало, задавай один-два конкретных вопроса.
- Ответ не длиннее 500 слов.

Доступные формы: Прямая, Г-образная, П-образная.
Ручки: Современный, Классический.
Позиция ручки: Лево, Центр, Право.

{_materials_section()}

{get_tools_schema()}

Контракт ответа: верни только валидный JSON без markdown-блоков и текста вокруг:
{{
  "reply_text": "...",
  "actions": {{
    "render_partition": {{...}} | null,
    "schedule_measurement": {{...}} | null,
    "update_client_profile": {{...}} | null,
    "state_patch": {{"mode": "...", "step": "...", "collected_params": {{}}}} | null
  }}
}}

PROFILE CONTEXT:
{profile_text}

STATE CONTEXT:
{json.dumps(state, ensure_ascii=False, default=str)}

CONVERSATION HISTORY:
{chr(10).join(history_lines[-20:])}

USER MESSAGE:
{user_message}
""".strip()

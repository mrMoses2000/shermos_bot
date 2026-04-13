"""Prompt assembler for Gemini CLI.

Builds a complete prompt that includes:
- System role & rules
- Available materials from config
- Tool/action definitions
- Current FSM state + MISSING params (critical for conversation flow)
- Client profile
- Conversation history
- Current user message
"""

from __future__ import annotations

import json
from typing import Any

from src.engine.fsm import format_summary, get_missing_params
from src.llm.tools_schema import get_tools_schema
from src.utils.config_manager import config

# Human-readable labels for render parameters
_PARAM_LABELS = {
    "shape": "Форма перегородки (Прямая / Г-образная / П-образная)",
    "height": "Высота (метры, 0.5–5.0)",
    "width_a": "Ширина A (метры, 0.3–10.0)",
    "width_b": "Ширина B (метры, для Г- и П-образной)",
    "width_c": "Ширина C (метры, для П-образной)",
    "glass_type": "Тип стекла (номер 1–4)",
    "frame_color": "Цвет профиля (номер 1–5)",
    "rows": "Кол-во рядов (целое число)",
    "cols": "Кол-во колонок (целое число)",
}


def _materials_section() -> str:
    glass = config.get_all_materials("glass_types")
    frames = config.get_all_materials("frame_colors")
    glass_lines = [f'  {key}: {value.get("name", key)}' for key, value in glass.items()]
    frame_lines = [f'  {key}: {value.get("name", key)}' for key, value in frames.items()]
    return (
        "Типы стекла:\n"
        + "\n".join(glass_lines)
        + "\n\nЦвета профиля:\n"
        + "\n".join(frame_lines)
    )


def _missing_params_section(state: dict[str, Any]) -> str:
    """Build explicit list of parameters Gemini still needs to collect."""
    collected = state.get("collected_params", {})
    shape = collected.get("shape")
    missing = get_missing_params(collected, shape)
    if not missing:
        return "ВСЕ ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ СОБРАНЫ. Покажи резюме и спроси: «Рендерить?»"
    lines = ["Ещё не собраны (спроси у клиента):"]
    for key in missing:
        label = _PARAM_LABELS.get(key, key)
        lines.append(f"  - {label}")
    return "\n".join(lines)


def _slots_section(available_slots: dict[str, list[str]] | None) -> str:
    """Format available measurement slots for the prompt."""
    if not available_slots:
        return "(Данные о слотах не загружены — спроси клиента о желаемой дате, потом уточним время)"
    lines = []
    for date, slots in available_slots.items():
        if slots:
            lines.append(f"  {date}: {', '.join(slots)}")
        else:
            lines.append(f"  {date}: всё занято")
    if not lines:
        return "Нет данных о свободных слотах."
    return "Свободное время (предлагай клиенту из этого списка):\n" + "\n".join(lines)


def _collected_summary(state: dict[str, Any]) -> str:
    """Show what's already collected in human-readable form."""
    collected = state.get("collected_params", {})
    if not collected:
        return "Пока ничего не собрано."
    return format_summary(collected)


def build_prompt(
    user_message: str,
    client_profile: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    chat_messages: list[dict[str, Any]],
    available_slots: dict[str, list[str]] | None = None,
) -> str:
    profile_text = "Новый клиент — имя/телефон неизвестны."
    if client_profile:
        name = client_profile.get("name", "—")
        phone = client_profile.get("phone", "—")
        address = client_profile.get("address", "—")
        profile_text = f"Имя: {name}, Телефон: {phone}, Адрес: {address}"

    state = conversation_state or {"mode": "idle", "step": None, "collected_params": {}}
    history_lines = []
    for message in chat_messages:
        role = "Клиент" if message.get("role") == "user" else "Ассистент"
        history_lines.append(f"{role}: {message.get('text', '')}")

    return f"""Ты — умный консультант компании Shermos по стеклянным перегородкам.
Твоя задача: вести диалог с клиентом в Telegram, собирая параметры для 3D-визуализации.

═══ ПРАВИЛА ═══

1. ЯЗЫК: всегда отвечай на русском.
2. ФОРМАТ: Telegram HTML (<b>, <i>, \\n). НИКОГДА markdown.
3. ВЫХОД: ТОЛЬКО валидный JSON. Без ```json```, без текста вокруг.
4. ДЛИНА: reply_text — макс. 300 слов. Будь кратким и конкретным.
5. ВОПРОСЫ: задавай 1-2 вопроса за раз, не больше. Не перегружай клиента.
6. НЕ ВЫДУМЫВАЙ: если клиент не назвал параметр — спроси. Не подставляй случайные значения.
7. УМНЫЕ ПОДСКАЗКИ: предлагай популярные варианты. Например: «Чаще всего берут прозрачное стекло (тип 1) и белый профиль (цвет 1)».

═══ СТРАТЕГИЯ ДИАЛОГА ═══

Шаг 1 (idle → collecting): Спроси форму перегородки и общие размеры.
  Пример: «Какую форму перегородки хотите? Прямая стена, Г-образный угол, или П-образная ниша?»

Шаг 2 (collecting): Спроси тип стекла и цвет профиля.
  Покажи варианты списком. Предложи популярный вариант.

Шаг 3 (collecting): Уточни секции (rows/cols), ручки если нужны.
  Разумные дефолты: rows=1, cols=2, без ручки. Спроси: «По умолчанию 2 секции, подойдёт?»

Шаг 4 (confirming): Когда всё собрано — покажи резюме и спроси: «Рендерить?»

Шаг 5 (rendering): После подтверждения клиента — вызови render_partition.

ВАЖНО: Если клиент даёт несколько параметров сразу — бери все. Не переспрашивай то, что уже сказано.
ВАЖНО: Если клиент хочет записаться на замер вместо рендера — переключись на schedule_measurement.
ВАЖНО: state_patch ОБЯЗАТЕЛЕН в КАЖДОМ ответе, чтобы сохранять прогресс.

═══ ДОСТУПНЫЕ МАТЕРИАЛЫ ═══

{_materials_section()}

Доступные формы: Прямая, Г-образная (2 стены), П-образная (3 стены).
Ручки: Современный / Классический. Позиция: Лево / Центр / Право.

═══ ДЕЙСТВИЯ (actions) ═══

{get_tools_schema()}

═══ ФОРМАТ JSON-ОТВЕТА ═══

Верни СТРОГО такой JSON (и ничего кроме него):
{{
  "reply_text": "Текст ответа клиенту в Telegram HTML",
  "actions": {{
    "render_partition": {{ ... все параметры ... }} | null,
    "schedule_measurement": {{ ... }} | null,
    "update_client_profile": {{ ... }} | null,
    "state_patch": {{ "mode": "...", "step": "текущий_шаг", "collected_params": {{ ... все собранные параметры ... }} }} | null
  }}
}}

═══ ТЕКУЩЕЕ СОСТОЯНИЕ ДИАЛОГА ═══

Режим FSM: {state.get("mode", "idle")}
Шаг: {state.get("step", "начало")}

{_collected_summary(state)}

{_missing_params_section(state)}

═══ ПРОФИЛЬ КЛИЕНТА ═══

{profile_text}

═══ ДОСТУПНЫЕ СЛОТЫ ДЛЯ ЗАМЕРА ═══

{_slots_section(available_slots)}

═══ ИСТОРИЯ ДИАЛОГА (последние сообщения) ═══

{chr(10).join(history_lines[-20:]) if history_lines else "(Новый диалог — поприветствуй клиента!)"}

═══ СООБЩЕНИЕ КЛИЕНТА ═══

{user_message}""".strip()

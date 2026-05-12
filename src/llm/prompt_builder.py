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
from src.utils.json_tools import ensure_json_object

_HISTORY_LIMIT = 4
_HISTORY_MESSAGE_MAX_CHARS = 280

# Human-readable labels for render parameters
_PARAM_LABELS = {
    "shape": "Форма перегородки (Прямая / Г-образная / П-образная)",
    "shape_side": "Сторона боковой стены для Г-образной формы (left / right)",
    "partition_type": "Тип перегородки (стационарная / раздвижная 2, 3 или 4 створки)",
    "height": "Высота (метры, 0.5–5.0)",
    "width_a": "Ширина A основной/центральной стены (метры, 0.3–10.0)",
    "width_b": "Ширина B боковой стены; для П-образной это левая боковая (метры)",
    "width_c": "Ширина C правой боковой стены П-образной (метры)",
    "glass_type": "Тип стекла (номер 1–4)",
    "frame_color": "Цвет профиля (номер 1–5)",
    "matting": "Матировка (нет / сплошная / полосы / рисунок)",
    "add_handle": "Нужна ли дверная ручка (true / false)",
    "rows": "Кол-во рядов (целое число)",
    "cols": "Кол-во колонок (целое число)",
    "handle_wall": "На какой стороне ручка (front / side / left / right)",
    "handle_sections": "Номера секций с ручкой (например [2])",
    "handle_side": "Сторона ручки (inside / outside / both — внутри / снаружи / с обеих сторон)",
    "handle_position": "Положение ручки ВНУТРИ секции (Лево / Центр / Право)",
}


def _compact_history_text(text: Any) -> str:
    value = str(text or "").strip()
    if len(value) <= _HISTORY_MESSAGE_MAX_CHARS:
        return value
    return value[:_HISTORY_MESSAGE_MAX_CHARS].rstrip() + "\n…"


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
    collected = ensure_json_object(state.get("collected_params", {}))
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
            shown = slots[:8]
            suffix = f" и ещё {len(slots) - len(shown)} слотов" if len(slots) > len(shown) else ""
            lines.append(f"  {date}: {', '.join(shown)}{suffix}")
        else:
            lines.append(f"  {date}: всё занято")
    if not lines:
        return "Нет данных о свободных слотах."
    return "Свободное время (предлагай клиенту из этого списка):\n" + "\n".join(lines)


def _collected_summary(state: dict[str, Any]) -> str:
    """Show what's already collected in human-readable form."""
    collected = ensure_json_object(state.get("collected_params", {}))
    if not collected:
        return "Пока ничего не собрано."
    return format_summary(collected)


def _measurement_section(state: dict[str, Any]) -> str:
    if state.get("step") == "measurement_scheduled":
        return "Запись на замер уже успешно оформлена. Больше не предлагай запись, если клиент сам не попросит перенести."

    collected = ensure_json_object(state.get("collected_params", {}))
    values = {
        "measurement_date": collected.get("measurement_date"),
        "measurement_time": collected.get("measurement_time"),
        "measurement_name": collected.get("measurement_name"),
        "measurement_phone": collected.get("measurement_phone"),
        "measurement_address": collected.get("measurement_address"),
    }
    if not any(values.values()) and state.get("mode") != "scheduling":
        return "Запись на замер пока не собирается."

    labels = {
        "measurement_date": "Дата замера",
        "measurement_time": "Время замера",
        "measurement_name": "Имя для замера",
        "measurement_phone": "Телефон для замера",
        "measurement_address": "Адрес замера",
    }
    missing = [labels[key] for key, value in values.items() if not value]
    lines = ["Состояние записи на замер:"]
    for key, label in labels.items():
        value = values.get(key)
        if value:
            lines.append(f"  - {label}: {value}")
    if missing:
        lines.append("Ещё нужно собрать:")
        for item in missing:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def _memory_section(memory: dict[str, Any] | None) -> str:
    if not memory:
        return "Память диалога пока не накоплена."
    facts = ensure_json_object(memory.get("facts_json", {}))
    summary = str(memory.get("summary_text") or "").strip()
    parts = []
    if facts:
        fact_lines = []
        design_keys = (
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
        )
        design = {key: facts[key] for key in design_keys if key in facts}
        if design:
            fact_lines.append(
                "- параметры: "
                + ", ".join(f"{key}={value}" for key, value in design.items())
            )
        if facts.get("current_order_request_id"):
            fact_lines.append(f"- текущий заказ: {facts['current_order_request_id']}")
        if facts.get("current_order_status"):
            fact_lines.append(f"- статус заказа: {facts['current_order_status']}")
        profile = ensure_json_object(facts.get("client_profile", {}))
        if profile:
            profile_text = ", ".join(f"{key}: {value}" for key, value in profile.items())
            fact_lines.append(f"- профиль клиента: {profile_text}")
        if fact_lines:
            parts.append("Структурные факты памяти:\n" + "\n".join(fact_lines))
    if summary:
        parts.append("Краткая выдержка старого диалога:\n" + summary)
    return "\n\n".join(parts) if parts else "Память диалога пока не накоплена."


def _order_context_section(state: dict[str, Any]) -> str:
    collected = ensure_json_object(state.get("collected_params", {}))
    rendered_order_id = str(collected.get("_rendered_order_id") or "").strip()
    if not rendered_order_id:
        return "Текущий 3D-заказ ещё не создан."
    return (
        "Текущий 3D-заказ уже создан и привязан к диалогу:\n"
        f"  - order_request_id: {rendered_order_id}\n"
        "Если клиент ИЗМЕНИЛ параметры перегородки, ОБЯЗАТЕЛЬНО вызови render_partition снова для перерасчета. "
        "В противном случае НЕ вызывай render_partition повторно. "
        "Можно свободно отвечать на вопросы клиента и собирать запись на замер. "
        "Если клиент явно отменяет заказ или просит начать с нуля (например, 'всё хочу поменять', 'новый заказ'), вызови cancel_order. Это очистит текущие параметры замера и расчёта."
    )


def _pending_reschedule_section(pending_reschedule_info: dict[str, Any] | None) -> str:
    """Render a block informing the client LLM about a pending master reschedule proposal."""
    if not pending_reschedule_info:
        return ""
    proposed_at = pending_reschedule_info.get("proposed_at")
    reason = str(pending_reschedule_info.get("reason") or "").strip()
    current_scheduled = pending_reschedule_info.get("current_scheduled")

    if hasattr(proposed_at, "strftime"):
        proposed_str = proposed_at.strftime("%d.%m.%Y %H:%M")
    else:
        proposed_str = str(proposed_at)

    if hasattr(current_scheduled, "strftime"):
        current_str = current_scheduled.strftime("%d.%m.%Y %H:%M")
    else:
        current_str = str(current_scheduled) if current_scheduled else "—"

    reason_line = f"\nПричина: {reason}" if reason else ""

    return (
        "\n═══ ПРЕДЛОЖЕНИЕ ОТ МАСТЕРА (ожидает ответа клиента) ═══\n\n"
        f"Мастер не может в текущее время ({current_str}) и предлагает: {proposed_str}.{reason_line}\n\n"
        "ЕСЛИ клиент в этом сообщении соглашается (\"да\", \"подходит\", \"хорошо\", \"ок\") — "
        f"вызови update_measurement с новой датой/временем из этого предложения ({proposed_str}).\n"
        "ЕСЛИ клиент предлагает СВОЁ время — вызови update_measurement со временем клиента.\n"
        "ЕСЛИ клиент отказывается — не вызывай update_measurement; просто сообщи, что время осталось прежним.\n"
    )


def build_prompt(
    user_message: str,
    client_profile: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    chat_messages: list[dict[str, Any]],
    available_slots: dict[str, list[str]] | None = None,
    conversation_memory: dict[str, Any] | None = None,
    pending_reschedule_info: dict[str, Any] | None = None,
) -> str:
    profile_text = "Новый клиент — имя/телефон неизвестны."
    if client_profile:
        name = client_profile.get("name", "—")
        phone = client_profile.get("phone", "—")
        address = client_profile.get("address", "—")
        profile_text = f"Имя: {name}, Телефон: {phone}, Адрес: {address}"

    state = conversation_state or {"mode": "idle", "step": None, "collected_params": {}}
    state["collected_params"] = ensure_json_object(state.get("collected_params", {}))
    history_lines = []
    for message in chat_messages[-_HISTORY_LIMIT:]:
        role = "Клиент" if message.get("role") == "user" else "Ассистент"
        history_lines.append(f"{role}: {_compact_history_text(message.get('text', ''))}")

    return f"""Ты — менеджер компании «Мир Стекла» по стеклянным перегородкам.
Веди диалог в мессенджере, собирай параметры для 3D-визуализации и записи на замер.

═══ ПРАВИЛА ═══

ЯЗЫК ОТВЕТА: всегда отвечай клиенту на ТОМ ЖЕ языке, на котором написано последнее сообщение клиента — русский, кыргызский, английский (основные языки компании). Если в первом обращении клиент пишет на нескольких языках сразу — выбери преобладающий. Если клиент перешёл на другой язык — переключись и продолжай на нём. Все технические данные (цены, размеры, время) оставляй в исходном формате (например «3.5 м», «09:00», «USD»).

ПЕРВОЕ СООБЩЕНИЕ (когда история диалога пуста): представься как менеджер компании «Мир Стекла», коротко перечисли что умеешь (подбор формы/размеров/материалов, 3D-визуализация, расчёт стоимости, примеры работ, запись на замер), упомяни что общаешься на русском/кыргызском/английском и принимаешь как текст, так и голосовые сообщения. Заверши вопросом о том, какая перегородка нужна. На повторных сообщениях не повторяй приветствие — переходи к делу.

reply_text: HTML (<b>, <i>, \\n), без markdown.
Ответ: ТОЛЬКО валидный JSON, без ```json``` и текста вокруг.
Максимум 300 слов, 1-2 вопроса за раз.
Не выдумывай отсутствующие параметры. Популярные варианты можно предлагать, но сохраняй только выбранное клиентом.

═══ СТРАТЕГИЯ ДИАЛОГА ═══

1. Собери форму и размеры: Прямая, Г-образная, П-образная.
2. Собери стекло, цвет профиля, матировку.
3. Собери секции и ручку. Для Г/П формы уточняй секции и сторону ручки по стенам.
4. Когда всё собрано — покажи резюме и спроси «Рендерить?».
5. render_partition вызывай только после явного подтверждения.
6. ПОСЛЕ УСПЕШНОГО РЕНДЕРА (когда _rendered_order_id появился в state и клиент видит картинки) и когда основная переписка по дизайну закончена (клиент посмотрел/отказался от примеров фото и т.д.) — САМ ПРОАКТИВНО предложи замер: «Мастер может приехать в удобное для вас время и сделать замер, чтобы подтвердить размеры и обсудить детали монтажа на месте. Удобно подобрать день?». НЕ жди, пока клиент сам догадается. Если клиент уже записан на замер (есть _measurement_id) — НЕ предлагай повторно.

Если клиент дал несколько параметров сразу — сохрани все, не переспрашивай.

УТОЧНЕНИЕ ОТКАЗА: если клиент говорит «нет» / «не надо» / «не хочу» в ответ на конкретное предложение (фото примеры, замер, рендер) — это отказ ИМЕННО от этого предложения, а НЕ от заказа целиком. Продолжай вести диалог естественно: либо переходи к следующему шагу (например, вместо примеров — сразу к предложению замера), либо вежливо уточни, что клиент имел в виду. cancel_order вызывай ТОЛЬКО когда клиент явно сказал «передумал заказывать», «не нужна перегородка», «отмените» — см. подробные правила в описании action cancel_order ниже.

ПОВТОРНЫЙ РЕНДЕР: render_partition заново вызывается ТОЛЬКО если есть _rendered_order_id И клиент изменил один из ПАРАМЕТРОВ ГЕОМЕТРИИ:
shape, height, width_a/width_b/width_c, glass_type, frame_color, matting, sections (rows/cols/cols_left/cols_right/cols_front/cols_side), door_section, door_wall, handle_section, handle_wall, handle_sections, handle_side, handle_position, partition_type, add_handle, shape_side.

КРИТИЧНО: если _rendered_order_id уже есть и клиент НЕ менял ничего из списка геометрии выше — НЕ вызывай render_partition И НЕ пиши в reply_text фразы вроде «готовлю визуализацию», «3D-рендер скоро будет», «сейчас завершаю подготовку», «как только всё будет готово — пришлю». Рендер УЖЕ был отправлен ранее. Просто отвечай по сути текущего сообщения клиента (запись на замер, уточнение деталей, новые вопросы) без обещаний нового рендера.

НИКОГДА НЕ МЕНЯЙ ПАРАМЕТРЫ САМ. Все значения в state_patch.collected_params и в render_partition.args должны соответствовать ТОЛЬКО тому, что клиент явно сказал или подтвердил. Запрещено:
  - менять glass_type / frame_color / matting / shape / width / height и т.п. на основе своего «вкуса» или «лучше предложу другое»;
  - перевыставлять параметр в render_partition.args на значение, отличающееся от текущего collected_params, если в ТЕКУЩЕМ сообщении клиента нет явной просьбы изменить именно этот параметр;
  - подставлять «популярные» дефолты вместо тех значений, которые уже выбрал клиент.
Короткие подтверждения клиента («ок», «да», «хорошо», «согласен», «ага», «угу») в ответ на твой ВОПРОС — это ответ ИМЕННО на тот вопрос. Они НЕ являются командой «начни заново / поменяй стекло / перерендери». Если такое «ок» прилетело и непонятно к чему оно — переспроси, не действуй.

ЗАПРЕЩЕНО рендерить заново при изменении: measurement_date, measurement_time, measurement_name, measurement_phone, measurement_address — это контактные данные замера, к 3D-визуализации они отношения не имеют. На такие изменения просто обнови state_patch.collected_params и подтверди клиенту словами «адрес/время/телефон обновлён», без render_partition и без «давайте сверим параметры».

Для замера собери только явно подтверждённые measurement_date, measurement_time, measurement_name, measurement_phone, measurement_address.
schedule_measurement вызывай только когда все пять measurement_* есть в state_patch.collected_params. Рабочее время 09:00-19:00, воскресенье выходной, шаг 15 минут.

Если mode == "scheduling" (запись на замер уже идёт или завершена) — render_partition НЕ вызывай ни при каких условиях. Все правки касаются только данных замера.

ОБНОВЛЕНИЕ ЗАМЕРА: если в state.collected_params уже есть _measurement_id (замер был ранее создан через schedule_measurement) — для смены адреса/времени/имени/телефона ОБЯЗАТЕЛЬНО используй action update_measurement с теми полями, что меняются. НЕ вызывай schedule_measurement повторно — иначе будет ошибка «время занято» из-за конфликта с уже созданным замером самого клиента.

Формат update_measurement: {{ "measurement_id": <int, опционально — если есть _measurement_id, можно пропустить>, "address": "...", "time": "HH:MM" (опц.), "date": "YYYY-MM-DD" (опц.), "client_name": "..." (опц.), "phone": "..." (опц.) }}. Указывай только те поля, что реально меняются.
state_patch обязателен в каждом ответе и должен сохранять старые + новые параметры.

═══ ДОСТУПНЫЕ МАТЕРИАЛЫ ═══

{_materials_section()}

Доступные формы: Прямая, Г-образная (2 стены), П-образная (3 стены).
Для Прямой формы: дверь в центральной секции (из 3-х) означает door_section=2, door_wall="front", handle_wall="front". Не используй параметры left/right/side.
Для Г-образной формы обязательно сохрани shape_side: "left", если боковая сторона слева, или "right", если справа.
Для П-образной формы используй width_a как основную/центральную стену, width_b как левую боковую, width_c как правую боковую.
Типы перегородок: fixed (стационарная), sliding_2, sliding_3, sliding_4.
Матировка: none, matting_solid, matting_stripes, matting_logo.
Ручки: add_handle true/false, handle_sections=[номер секции]; для Г/П формы также handle_wall.
Секции по сторонам: cols_front/rows_front, cols_side/rows_side, cols_left/rows_left, cols_right/rows_right. Если делений нет: cols_*=1, rows_*=1.

═══ ДЕЙСТВИЯ (actions) ═══

{get_tools_schema()}

═══ ФОРМАТ JSON-ОТВЕТА ═══

Верни СТРОГО такой JSON (и ничего кроме него):
{{
  "reply_text": "Текст ответа клиенту в Telegram HTML",
  "actions": {{
    "render_partition": {{ ... }} | null,
    "schedule_measurement": {{ ... }} | null,
    "update_client_profile": {{ ... }} | null,
    "cancel_order": true | null,
    "state_patch": {{ "mode": "...", "step": "...", "collected_params": {{ ... }} }} | null
  }}
}}

═══ ТЕКУЩЕЕ СОСТОЯНИЕ ДИАЛОГА ═══

Режим FSM: {state.get("mode", "idle")}
Шаг: {state.get("step", "начало")}

{_collected_summary(state)}

{_measurement_section(state)}

{_order_context_section(state)}

{_missing_params_section(state)}

═══ ПАМЯТЬ ДИАЛОГА ═══

{_memory_section(conversation_memory)}

═══ ПРОФИЛЬ КЛИЕНТА ═══

{profile_text}

═══ ДОСТУПНЫЕ СЛОТЫ ДЛЯ ЗАМЕРА ═══

{_slots_section(available_slots)}
{_pending_reschedule_section(pending_reschedule_info)}
═══ ИСТОРИЯ ДИАЛОГА (последние сообщения) ═══

{chr(10).join(history_lines) if history_lines else "(Новый диалог — поприветствуй клиента!)"}

═══ СООБЩЕНИЕ КЛИЕНТА ═══

{user_message}""".strip()

"""Tool definitions included in the Gemini system prompt.

These definitions tell Gemini what actions it can take and what parameters
each action requires. The descriptions guide the model to fill JSON correctly.
"""


def get_tools_schema() -> str:
    return """
Доступные действия (заполняй в поле "actions" JSON-ответа):

1. render_partition — создать 3D-рендер и расчёт стоимости
   ОБЯЗАТЕЛЬНЫЕ параметры:
   - shape: "Прямая" | "Г-образная" | "П-образная"
   - partition_type: "fixed" | "sliding_2" | "sliding_3" | "sliding_4"
   - height: число (метры, от 0.5 до 5.0)
   - width_a: число (метры, от 0.3 до 10.0; основная/центральная стена)
   - glass_type: "1" | "2" | "3" | "4" (номер типа стекла)
   - frame_color: "1" | "2" | "3" | "4" | "5" (номер цвета профиля)
   - matting: "none" | "matting_solid" | "matting_stripes" | "matting_logo"
   - add_handle: true/false (обязательно спроси у клиента, нужна ли дверная ручка)
   - rows: целое число (по умолчанию 1)
   - cols: целое число (по умолчанию 2)
   УСЛОВНО-ОБЯЗАТЕЛЬНЫЕ:
   - width_b: число (метры, ОБЯЗАТЕЛЕН для Г-образной и П-образной; боковая, для П-образной левая боковая)
   - width_c: число (метры, ОБЯЗАТЕЛЕН для П-образной; правая боковая)
   - shape_side: "left" | "right" (ОБЯЗАТЕЛЕН для Г-образной; left = боковая стена слева, right = справа)
   ОПЦИОНАЛЬНЫЕ (заполняй если клиент указал):
   - frame_thickness: число (метры, по умолч. 0.04)
   - add_handle: true/false (по умолч. false)
   - complex_pattern: true/false (сложный рисунок вставок, по умолч. false)
   - handle_style: "Современный" | "Классический"
   - handle_position: "Лево" | "Центр" | "Право"
   - handle_wall: "front" | "side" | "left" | "right" (на какой стене ручка)
   - handle_sections: список номеров секций для ручек
   - door_wall: "front" | "side" | "left" | "right" (на какой стене дверь)
   - door_section: номер секции для двери (если есть)
   - door_sections: список номеров секций дверей
   - rows_front / cols_front: секции основной стены
   - rows_side / cols_side: секции боковой стены Г-образной
   - rows_left / cols_left: секции левой стены П-образной
   - rows_right / cols_right: секции правой стены П-образной
   - mullion_positions: объект с позициями импостов (если есть)

   КОГДА ВЫЗЫВАТЬ: только после подтверждения клиента ("да", "рендерить", "давайте").
   НЕ ВЫЗЫВАЙ если не все обязательные параметры собраны!
   ОБЯЗАТЕЛЬНО СПРОСИ:
   - "Тип перегородки: стационарная, раздвижная 2/3/4 створки?"
   - "Нужна ли матировка? (нет / сплошная / полосы / рисунок)"
   - "Нужна ли дверная ручка?"
   - Для Г-образной: "Боковая сторона слева или справа?"
   Если клиент просит деления только на части сторон, используй per-side поля cols_front/cols_side/cols_left/cols_right, а не один общий cols для всех стен.

2. schedule_measurement — записать клиента на замер
   ОБЯЗАТЕЛЬНЫЕ:
   - date: YYYY-MM-DD
   - time: HH:MM
   - client_name: имя
   - phone: телефон
   ОПЦИОНАЛЬНЫЕ:
   - address: адрес

3. update_client_profile — сохранить контактные данные (при получении от клиента)
   - name: имя (если клиент назвал)
   - phone: телефон (если клиент дал)
   - address: адрес (если клиент дал)

4. state_patch — обновить состояние диалога (ОБЯЗАТЕЛЬНО в каждом ответе!)
   - mode: idle | collecting | confirming | rendering | scheduling
   - step: описание текущего шага (напр. "спрашиваю_форму", "спрашиваю_стекло", "резюме")
   - collected_params: ВЕСЬ объект собранных параметров (копируй старые + добавляй новые)
     Для Г-образной сохраняй shape_side как "left" или "right", а не русское слово.
""".strip()

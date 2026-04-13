"""Tool definitions included in the Gemini system prompt."""


def get_tools_schema() -> str:
    return """
Доступные действия:

1. render_partition
   Назначение: создать 3D-рендер стеклянной перегородки и расчет стоимости.
   Параметры:
   - shape: "Прямая" | "Г-образная" | "П-образная"
   - height: число, метры
   - width_a: число, метры
   - width_b: число, метры, требуется для Г-образной и П-образной
   - width_c: число, метры, требуется для П-образной
   - glass_type: "1" | "2" | "3" | "4"
   - frame_color: "1" | "2" | "3" | "4" | "5"
   - rows: целое число
   - cols: целое число
   - frame_thickness: число, метры
   - add_handle: boolean
   - handle_style: "Современный" | "Классический"
   - handle_position: "Лево" | "Центр" | "Право"
   - door_section: номер секции, если есть дверь
   - mullion_positions: объект с пользовательскими позициями импостов, если есть

2. schedule_measurement
   Назначение: записать клиента на замер.
   Параметры:
   - date: YYYY-MM-DD
   - time: HH:MM
   - client_name: имя клиента
   - phone: телефон
   - address: адрес

3. update_client_profile
   Назначение: сохранить контактные данные клиента.
   Параметры:
   - name: имя
   - phone: телефон
   - address: адрес

4. state_patch
   Назначение: обновить состояние диалога.
   Параметры:
   - mode: idle | collecting | confirming | rendering | scheduling
   - step: текущий шаг
   - collected_params: собранные параметры перегородки
""".strip()

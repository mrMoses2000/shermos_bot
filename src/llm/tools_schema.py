"""Tool definitions included in the Gemini system prompt.

These definitions tell Gemini what actions it can take and what parameters
each action requires. The descriptions guide the model to fill JSON correctly.
"""


def get_tools_schema() -> str:
    return """
Доступные действия (заполняй в поле "actions" JSON-ответа):

1. render_partition — создать 3D-рендер и расчет.
   Вызывай только после явного подтверждения клиента и только когда все обязательные поля собраны.
   Базовые поля: shape, partition_type, height, width_a, glass_type, frame_color, matting, add_handle.

   shape — СТРОГО одна из трёх строк, без сокращений и без хвостов в скобках:
     "Прямая" | "Г-образная" | "П-образная".
   НЕ передавай "П", "Р", "P", "U", "L" или "П-образная (ниша)" — только полные канонические значения.

   СЕКЦИИ — зависят от формы (это разные параметры, НЕ дублируй их):
   - Прямая: rows + cols (одна стена).
   - Г-образная: rows_front + cols_front + rows_side + cols_side + width_b + shape_side ("left"|"right"). НЕ передавай rows/cols.
   - П-образная: rows_front+cols_front + rows_left+cols_left + rows_right+cols_right + width_b + width_c. НЕ передавай rows/cols.

   Для Прямой формы: дверь по центру в 3 секциях означает door_section=2 и door_wall="front". Ручка тоже на "front".
   Если нужна ручка: handle_sections обязателен, а для Г/П формы ещё handle_wall ("front"|"side"|"left"|"right").
   handle_side: "inside" (внутри помещения), "outside" (снаружи) или "both" (с обеих сторон). Для душевых перегородок чаще "outside" — дверь открывается на себя.
   handle_position — положение ручки ВНУТРИ выбранной секции по горизонтали:
     "Лево"  — у левого края секции
     "Центр" — посередине секции
     "Право" — у правого края секции (по умолчанию)
   Используй то значение, которое попросит клиент. Если он явно не указал — оставь "Право".

2. schedule_measurement — СОЗДАТЬ новую запись на замер. Только если у клиента ещё НЕТ активного замера (т.е. в state.collected_params._measurement_id отсутствует).
   Поля: date YYYY-MM-DD, time HH:MM, client_name, phone, address.
   Без address не вызывай. Рабочее время 09:00-19:00, воскресенье выходной, шаг 15 минут.

3. update_measurement — ОБНОВИТЬ существующий замер (когда _measurement_id уже есть в state). Используй именно это, а не schedule_measurement, иначе будет конфликт «время занято» с собственной записью клиента.
   Поля (все опц., указывай только меняющиеся): measurement_id (если в state нет _measurement_id), date, time, client_name, phone, address.

4. update_client_profile — сохранить явно названные name, phone, address.

5. cancel_order — только если клиент явно отменяет заказ или начинает заново.

6. state_patch — обязателен в каждом ответе.
   mode: idle | collecting | confirming | rendering | scheduling.
   collected_params: весь объект параметров, старые + новые.
   Для Г-образной shape_side всегда "left" или "right".
   Если есть _rendered_order_id, сохраняй его. При ИЗМЕНЕНИИ параметров вызови render_partition заново.
   Для замера храни только явно подтвержденные measurement_date/time/name/phone/address.
	""".strip()

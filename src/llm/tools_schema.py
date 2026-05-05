"""Tool definitions included in the Gemini system prompt.

These definitions tell Gemini what actions it can take and what parameters
each action requires. The descriptions guide the model to fill JSON correctly.
"""


def get_tools_schema() -> str:
    return """
Доступные действия (заполняй в поле "actions" JSON-ответа):

1. render_partition — создать 3D-рендер и расчет.
   Вызывай только после явного подтверждения клиента и только когда все обязательные поля собраны.
   Поля: shape, partition_type, height, width_a, glass_type, frame_color, matting, add_handle, rows, cols.
   Для Прямой формы: дверь по центру в 3 секциях означает door_section=2 и door_wall="front". Ручка тоже на "front".
   Для Г-образной добавь width_b и shape_side ("left"|"right"). Для П-образной добавь width_b и width_c.
   Если нужна ручка: handle_sections обязателен, а для Г/П формы ещё handle_wall ("front"|"side"|"left"|"right").
   Для сложных форм секции по сторонам храни в cols_front/cols_side/cols_left/cols_right и rows_*.

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

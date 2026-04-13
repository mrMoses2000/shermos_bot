"""Inline keyboard builders for Telegram."""


def _inline_keyboard(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def confirm_render_keyboard() -> dict:
    return _inline_keyboard(
        [
            [
                {"text": "✅ Рендерить", "callback_data": "confirm_render"},
                {"text": "❌ Отмена", "callback_data": "cancel_render"},
            ]
        ]
    )


def confirm_measurement_keyboard(date: str, time: str) -> dict:
    return _inline_keyboard(
        [
            [
                {
                    "text": "✅ Подтвердить",
                    "callback_data": f"confirm_measurement:{date}:{time}",
                },
                {"text": "❌ Отмена", "callback_data": "cancel_measurement"},
            ]
        ]
    )


def rate_render_keyboard(order_id: str) -> dict:
    return _inline_keyboard(
        [[{"text": f"⭐{score}", "callback_data": f"rate_render:{order_id}:{score}"} for score in range(1, 6)]]
    )


def manager_order_keyboard(order_id: str) -> dict:
    return _inline_keyboard(
        [
            [
                {"text": "✅ Confirmed", "callback_data": f"order_status:{order_id}:confirmed"},
                {"text": "🔧 In Progress", "callback_data": f"order_status:{order_id}:in_progress"},
            ],
            [
                {"text": "✅ Completed", "callback_data": f"order_status:{order_id}:completed"},
                {"text": "❌ Cancel", "callback_data": f"order_status:{order_id}:cancelled"},
            ],
        ]
    )


def open_mini_app_keyboard(url: str) -> dict:
    return _inline_keyboard([[{"text": "📊 Открыть CMS", "web_app": {"url": url}}]])

from src.bot.keyboards import (
    confirm_measurement_keyboard,
    confirm_render_keyboard,
    manager_order_keyboard,
    open_mini_app_keyboard,
    rate_render_keyboard,
)


def test_keyboard_contracts():
    assert confirm_render_keyboard()["inline_keyboard"][0][0]["callback_data"] == "confirm_render"
    measurement = confirm_measurement_keyboard("2026-01-01", "10:00")
    assert "2026-01-01" in measurement["inline_keyboard"][0][0]["callback_data"]
    assert len(rate_render_keyboard("o1")["inline_keyboard"][0]) == 5
    assert manager_order_keyboard("o1")["inline_keyboard"][0][0]["callback_data"] == (
        "order_status:o1:confirmed"
    )
    assert open_mini_app_keyboard("https://example.com")["inline_keyboard"][0][0]["web_app"][
        "url"
    ].startswith("https://")

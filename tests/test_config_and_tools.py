from src.config import Settings
from src.llm.tools_schema import get_tools_schema
from src.utils.query_parser import normalize_handle_position, normalize_render_params, normalize_shape


def test_settings_properties():
    settings = Settings(
        telegram_bot_token="client",
        telegram_webhook_secret="client-secret",
        manager_bot_token="manager",
        manager_webhook_secret="manager-secret",
        manager_chat_ids="1, 2",
    )

    assert settings.webhook_url_client.endswith("/webhook/client")
    assert settings.webhook_url_manager.endswith("/webhook/manager")
    assert settings.manager_chat_ids_list == [1, 2]
    assert settings.postgres_dsn.startswith("postgresql://")


def test_tools_schema_and_query_normalization():
    assert "render_partition" in get_tools_schema()
    assert normalize_shape("угловая") == "Г-образная"
    assert normalize_shape(None) == "Прямая"
    assert normalize_handle_position("слева") == "Лево"
    params = normalize_render_params({"shape": "u", "width_b": "", "width_c": 0, "door_section": 2})
    assert params["shape"] == "П-образная"
    assert params["width_b"] is None
    assert params["width_c"] is None
    assert params["door_sections"] == [2]

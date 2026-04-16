from src.config import Settings
from src.llm.tools_schema import get_tools_schema
from src.utils.query_parser import (
    normalize_handle_position,
    normalize_matting,
    normalize_partition_type,
    normalize_render_params,
    normalize_shape,
    normalize_shape_side,
)


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
    assert normalize_shape_side("слева") == "left"
    assert normalize_shape_side("справа") == "right"
    assert normalize_partition_type("3 створки") == "sliding_3"
    assert normalize_matting("полосы") == "matting_stripes"
    params = normalize_render_params({"shape": "u", "shape_side": "слева", "width_b": "", "width_c": 0, "door_section": 2})
    assert params["shape"] == "П-образная"
    assert params["shape_side"] == "left"
    assert params["partition_type"] == "sliding_2"
    assert params["matting"] == "none"
    assert params["width_b"] is None
    assert params["width_c"] is None
    assert params["door_sections"] == [2]

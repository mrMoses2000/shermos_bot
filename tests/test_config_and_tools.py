from src.config import Settings
from src.llm.tools_schema import get_tools_schema
from src.utils.query_parser import (
    normalize_handle_position,
    normalize_matting,
    normalize_partition_type,
    normalize_render_params,
    normalize_shape,
    normalize_shape_side,
    normalize_wall,
)


def test_settings_properties():
    settings = Settings(
        manager_whatsapp_numbers="+7-706-739-66-26, 77001234567",
    )

    assert settings.manager_whatsapp_numbers_list == ["77067396626", "77001234567"]
    assert settings.postgres_dsn.startswith("postgresql://")


def test_tools_schema_and_query_normalization():
    assert "render_partition" in get_tools_schema()
    assert normalize_shape("угловая") == "Г-образная"
    assert normalize_shape(None) == "Прямая"
    # Trailing parenthetical descriptors (Gemini sometimes appends "(ниша)" / "(угол)")
    # must be stripped so the canonical string survives validation.
    assert normalize_shape("П-образная (ниша)") == "П-образная"
    assert normalize_shape("Г-образная (угол)") == "Г-образная"
    assert normalize_shape("  Прямая  ") == "Прямая"
    # Single Cyrillic "Р" (U+0420 — "er") must NOT silently map to "П-образная";
    # it should fall through unchanged so the Pydantic Literal on
    # RenderPartitionAction.shape can reject it loudly.
    assert normalize_shape("Р") == "Р"
    assert normalize_handle_position("слева") == "Лево"
    assert normalize_shape_side("слева") == "left"
    assert normalize_shape_side("справа") == "right"
    assert normalize_wall("основная") == "front"
    assert normalize_wall("правой") == "right"
    assert normalize_partition_type("3 створки") == "sliding_3"
    assert normalize_matting("полосы") == "matting_stripes"
    params = normalize_render_params({
        "shape": "u",
        "shape_side": "слева",
        "handle_wall": "основная",
        "door_wall": "правой",
        "width_b": "",
        "width_c": 0,
        "door_section": 2,
    })
    assert params["shape"] == "П-образная"
    assert params["shape_side"] == "left"
    assert params["handle_wall"] == "front"
    assert params["door_wall"] == "right"
    assert params["partition_type"] == "sliding_2"
    assert params["matting"] == "none"
    assert params["width_b"] is None
    assert params["width_c"] is None
    assert params["door_sections"] == [2]

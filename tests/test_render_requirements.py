from src.engine.render_requirements import merge_render_params, missing_render_params


def test_missing_render_params_does_not_accept_model_defaults_as_collected_data():
    missing = missing_render_params({"shape": "Прямая", "height": 2, "width_a": 3})

    assert "partition_type" in missing
    assert "glass_type" in missing
    assert "frame_color" in missing
    assert "matting" in missing


def test_missing_render_params_requires_l_shape_side():
    missing = missing_render_params(
        {
            "shape": "Г-образная",
            "height": 2,
            "width_a": 3,
            "width_b": 1,
            "partition_type": "sliding_2",
            "glass_type": "1",
            "frame_color": "1",
            "matting": "none",
            "rows": 1,
            "cols": 2,
        }
    )

    assert missing == ["shape_side"]


def test_merge_render_params_preserves_current_order_draft_values():
    merged = merge_render_params(
        {"shape": "Г-образная", "shape_side": "left", "height": 2},
        {"width_a": 3, "width_b": 1},
    )

    assert merged == {"shape": "Г-образная", "shape_side": "left", "height": 2, "width_a": 3, "width_b": 1}

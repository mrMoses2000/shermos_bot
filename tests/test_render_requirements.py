from src.engine.render_requirements import merge_render_params, missing_render_params


def test_missing_render_params_does_not_accept_model_defaults_as_collected_data():
    missing = missing_render_params({"shape": "Прямая", "height": 2, "width_a": 3})

    assert "partition_type" in missing
    assert "glass_type" in missing
    assert "frame_color" in missing
    assert "matting" in missing
    assert "add_handle" in missing


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
            "add_handle": False,
            "rows": 1,
            "cols": 2,
        }
    )

    assert missing == ["shape_side"]


def test_missing_render_params_requires_handle_location_when_handle_enabled():
    missing = missing_render_params(
        {
            "shape": "Г-образная",
            "shape_side": "right",
            "height": 2,
            "width_a": 3,
            "width_b": 1,
            "partition_type": "fixed",
            "glass_type": "1",
            "frame_color": "1",
            "matting": "none",
            "add_handle": True,
            "rows": 1,
            "cols": 2,
        }
    )

    assert "handle_sections" in missing
    assert "handle_wall" in missing
    assert "handle_side" in missing


def test_merge_render_params_preserves_current_order_draft_values():
    merged = merge_render_params(
        {"shape": "Г-образная", "shape_side": "left", "height": 2},
        {"width_a": 3, "width_b": 1},
    )

    assert merged == {"shape": "Г-образная", "shape_side": "left", "height": 2, "width_a": 3, "width_b": 1, "glass_type": "1", "frame_color": "1", "matting": "none", "partition_type": "sliding_2", "handle_position": "Право"}

def test_missing_render_params_requires_handle_side_when_handle_enabled():
    """Phase 12: handle_side must be required when add_handle is True."""
    missing = missing_render_params(
        {
            "shape": "Прямая",
            "height": 2,
            "width_a": 3,
            "partition_type": "sliding_2",
            "glass_type": "1",
            "frame_color": "1",
            "matting": "none",
            "add_handle": True,
            "rows": 1,
            "cols": 2,
            "handle_sections": [2],
        }
    )
    assert "handle_side" in missing


def test_handle_side_not_required_when_no_handle():
    """handle_side must NOT be required when add_handle is False."""
    missing = missing_render_params(
        {
            "shape": "Прямая",
            "height": 2,
            "width_a": 3,
            "partition_type": "sliding_2",
            "glass_type": "1",
            "frame_color": "1",
            "matting": "none",
            "add_handle": False,
            "rows": 1,
            "cols": 2,
        }
    )
    assert "handle_side" not in missing


def test_shape_switch_contamination_is_cleaned_up():
    merged = merge_render_params(
        {
            "shape": "Г-образная",
            "shape_side": "left",
            "width_a": 3,
            "width_b": 1,
            "width_c": 2,
            "cols_left": 2,
            "cols_right": 2,
            "rows_front": 2,
            "cols_front": 1,
            "door_wall": "side",
            "handle_wall": "left"
        },
        {"shape": "Прямая", "rows": 1, "cols": 3, "door_section": 2}
    )

    assert merged["shape"] == "Прямая"
    assert "width_b" not in merged
    assert "width_c" not in merged
    assert "shape_side" not in merged
    assert "cols_left" not in merged
    assert "cols_right" not in merged
    assert "rows_front" not in merged
    assert "cols_front" not in merged
    assert merged.get("door_wall") == "front"
    assert merged.get("handle_wall") == "front"
    assert merged.get("door_sections") == [2]

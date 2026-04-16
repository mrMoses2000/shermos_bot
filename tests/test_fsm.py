from src.engine.fsm import format_summary, get_missing_params, is_valid_transition


def test_fsm_transitions_and_missing_params():
    assert is_valid_transition("idle", "collecting")
    assert not is_valid_transition("idle", "rendering")

    missing = get_missing_params({"shape": "П-образная", "height": 2.5, "width_a": 2})
    assert "width_b" in missing
    assert "width_c" in missing

    l_missing = get_missing_params({"shape": "Г-образная", "height": 2.5, "width_a": 2, "width_b": 1})
    assert "shape_side" in l_missing

    handle_missing = get_missing_params(
        {
            "shape": "П-образная",
            "height": 2.5,
            "width_a": 3,
            "width_b": 1,
            "width_c": 1,
            "partition_type": "fixed",
            "glass_type": "1",
            "frame_color": "1",
            "matting": "none",
            "add_handle": True,
            "rows": 1,
            "cols": 2,
        }
    )
    assert "handle_wall" in handle_missing
    assert "handle_sections" in handle_missing


def test_format_summary():
    summary = format_summary({"shape": "Прямая", "height": 2.6, "width_a": 3})

    assert "Параметры" in summary
    assert "Прямая" in summary


def test_format_summary_ignores_bad_payload():
    assert format_summary('{"shape": "Прямая"}').endswith("Прямая")
    assert format_summary("not json") == "<b>Параметры перегородки:</b>"

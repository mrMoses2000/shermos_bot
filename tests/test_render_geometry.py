from pathlib import Path

from src.render import create_partition


def test_p_shape_uses_width_a_as_main_wall():
    frame, glass, _handle = create_partition.create_partition_mesh(
        {
            "shape": "П-образная",
            "height": 2.4,
            "width_a": 4.0,
            "width_b": 1.0,
            "width_c": 2.0,
            "rows": 1,
            "cols": 2,
            "frame_thickness": 0.04,
            "frame_color": [0.1, 0.1, 0.1, 1],
            "glass_color": [0.8, 0.9, 1.0, 0.3],
        }
    )

    assert frame.extents[0] > 3.9
    assert glass.extents[0] > 3.8
    assert frame.extents[2] < 2.2


def test_wall_grid_supports_per_side_section_counts():
    params = {
        "rows": 1,
        "cols": 4,
        "rows_front": 2,
        "cols_front": 5,
        "rows_left": 1,
        "cols_left": 1,
        "rows_right": 3,
        "cols_right": 2,
    }

    assert create_partition._wall_grid(params, "front", "right", 1, 4) == (2, 5)
    assert create_partition._wall_grid(params, "left", "right", 1, 4) == (1, 1)
    assert create_partition._wall_grid(params, "right", "right", 1, 4) == (3, 2)


def test_renderer_uses_orthographic_camera_for_stable_section_spacing():
    source = Path("src/render/create_partition.py").read_text(encoding="utf-8")

    assert "pyrender.OrthographicCamera" in source
    assert "pyrender.PerspectiveCamera" not in source

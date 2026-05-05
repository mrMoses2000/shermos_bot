from pathlib import Path

import numpy as np
import pytest

from src.render import create_partition
from src.render.create_partition import _create_handle


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


# ---------------------------------------------------------------------------
# Phase 12 — handle_side geometry tests
# ---------------------------------------------------------------------------

def _centroid_z(part):
    """Return the mean Z coordinate of a mesh part's bounding box."""
    return part.bounds.mean(axis=0)[2]


def test_create_handle_inside_default_positive_z():
    """Default (inside) handle must have positive Z centroid."""
    parts = _create_handle("Современный", "Центр", 1.0, 2.0)
    assert parts, "Expected at least one mesh part"
    for p in parts:
        assert _centroid_z(p) > 0, f"Expected positive Z for inside handle, got {_centroid_z(p)}"


def test_create_handle_outside_negative_z():
    """Outside handle must have negative Z centroid."""
    parts = _create_handle("Современный", "Центр", 1.0, 2.0, handle_side="outside")
    assert parts, "Expected at least one mesh part"
    for p in parts:
        assert _centroid_z(p) < 0, f"Expected negative Z for outside handle, got {_centroid_z(p)}"


def test_create_handle_both_doubles_part_count():
    """'both' handle must produce exactly twice as many parts as 'inside' alone."""
    inside_parts = _create_handle("Современный", "Центр", 1.0, 2.0, handle_side="inside")
    both_parts = _create_handle("Современный", "Центр", 1.0, 2.0, handle_side="both")
    assert len(both_parts) == 2 * len(inside_parts), (
        f"Expected {2 * len(inside_parts)} parts for 'both', got {len(both_parts)}"
    )


def test_create_handle_classic_outside_negative_z():
    """Classic-style outside handle must also have negative Z."""
    parts = _create_handle("Классический", "Центр", 1.0, 2.0, handle_side="outside")
    assert parts
    for p in parts:
        assert _centroid_z(p) < 0, f"Expected negative Z for classic outside handle, got {_centroid_z(p)}"


def test_create_handle_both_has_positive_and_negative_z():
    """'both' must have parts on each side of the glass (both signs present)."""
    parts = _create_handle("Современный", "Центр", 1.0, 2.0, handle_side="both")
    z_values = [_centroid_z(p) for p in parts]
    assert any(z > 0 for z in z_values), "Expected at least one part with positive Z"
    assert any(z < 0 for z in z_values), "Expected at least one part with negative Z"

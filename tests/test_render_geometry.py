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


def _centroid_x(part):
    """Mean X coordinate of a mesh part's bounding box."""
    return (part.bounds[0][0] + part.bounds[1][0]) / 2.0


# ---------------------------------------------------------------------------
# handle_position — intra-section X placement
#
# The renderer derives x_pos from section_bounds via:
#   "Лево":  x_start + section_width * 0.1
#   "Центр": x_start + section_width * 0.5
#   "Право": x_end   - section_width * 0.1
# These tests pin the math to the contract documented in tools_schema.py so a
# stray edit to the offset constant or to x_start/x_end would fail loudly.
# ---------------------------------------------------------------------------

def test_create_handle_position_left_anchors_near_section_start():
    bounds = (0.5, 2.0)  # section_width = 1.5; expected x ≈ 0.5 + 0.15 = 0.65
    parts = _create_handle("Современный", "Лево", 1.0, 2.0, section_bounds=bounds)
    assert parts
    avg_x = sum(_centroid_x(p) for p in parts) / len(parts)
    assert 0.6 < avg_x < 0.75, f"'Лево' should sit near x_start; got {avg_x:.3f}"


def test_create_handle_position_center_anchors_in_section_middle():
    bounds = (0.5, 2.0)  # midpoint = 1.25
    parts = _create_handle("Современный", "Центр", 1.0, 2.0, section_bounds=bounds)
    assert parts
    avg_x = sum(_centroid_x(p) for p in parts) / len(parts)
    assert 1.20 < avg_x < 1.30, f"'Центр' should sit at section midpoint; got {avg_x:.3f}"


def test_create_handle_position_right_anchors_near_section_end():
    bounds = (0.5, 2.0)  # section_width = 1.5; expected x ≈ 2.0 - 0.15 = 1.85
    parts = _create_handle("Современный", "Право", 1.0, 2.0, section_bounds=bounds)
    assert parts
    avg_x = sum(_centroid_x(p) for p in parts) / len(parts)
    assert 1.75 < avg_x < 1.90, f"'Право' should sit near x_end; got {avg_x:.3f}"


def test_create_handle_position_left_center_right_are_distinct():
    """Sanity: the three positions must produce visibly different X coordinates,
    not all collapse to the default."""
    bounds = (0.5, 2.0)
    avg = {}
    for pos in ("Лево", "Центр", "Право"):
        parts = _create_handle("Современный", pos, 1.0, 2.0, section_bounds=bounds)
        avg[pos] = sum(_centroid_x(p) for p in parts) / len(parts)
    assert avg["Лево"] < avg["Центр"] < avg["Право"], (
        f"Positions should be ordered left-to-right; got {avg}"
    )
    # And spread should be at least half the section width — guards against a
    # regression where the offset coefficient gets tiny.
    assert avg["Право"] - avg["Лево"] > 0.7, f"Spread too small: {avg}"


def test_outer_frame_corners_do_not_overlap():
    """Regression: top/bottom rails must not extend into the corners owned
    by the left/right posts. Coincident cuboids at the same Z range cause
    z-fighting in pyrender (visible as doubled edges / corner bumps —
    reported by a client on 2026-05-10).

    Volume sanity: a 1×1-section frame should have exactly the volume of
    two posts (full height) + two interior-span rails. If rails extended
    full-width again, the corners would be double-covered and total volume
    would shrink (because trimesh deduplicates overlapping geometry on
    concatenation), or stay the same with z-fighting at runtime — either
    way the expected-vs-actual comparison fails.
    """
    width = 2.0
    height = 2.4
    thickness = 0.04
    frame, _glass, _handle = create_partition.create_partition_mesh(
        {
            "shape": "Прямая",
            "height": height,
            "width_a": width,
            "rows": 1,
            "cols": 1,
            "frame_thickness": thickness,
            "frame_color": [0.1, 0.1, 0.1, 1],
            "glass_color": [0.8, 0.9, 1.0, 0.3],
        }
    )
    expected_volume = (
        # Two posts, full height
        2 * thickness * height * thickness
        # Two rails, interior width only
        + 2 * (width - 2 * thickness) * thickness * thickness
    )
    assert frame.volume == pytest.approx(expected_volume, rel=0.01), (
        f"Frame volume {frame.volume:.6f} differs from non-overlapping "
        f"expectation {expected_volume:.6f} — corners likely overlap again."
    )

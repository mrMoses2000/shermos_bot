"""Unit tests for scene-theme dispatch in src/render/create_partition.

These tests do NOT touch pyrender (no GL context required) — they only
verify the pure helpers `_get_scene_theme` and `_build_studio_floor`,
plus the structure of `_SCENE_THEMES`. Renders themselves are exercised
by the existing test_render*.py suites and by manual server smoke.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.render import create_partition as cp


def test_known_theme_resolves_to_dict():
    theme = cp._get_scene_theme("light_studio")
    assert theme is cp._SCENE_THEMES["light_studio"]
    # Required keys for the renderer
    for key in ("bg_color", "ambient", "lights"):
        assert key in theme, f"theme missing {key}"


def test_unknown_theme_falls_back_to_dark_studio():
    theme = cp._get_scene_theme("totally-unknown")
    assert theme is cp._SCENE_THEMES["dark_studio"]


def test_dark_studio_keeps_legacy_values():
    """Регрессия: dark_studio должен совпадать с историческими значениями."""
    dark = cp._SCENE_THEMES["dark_studio"]
    assert dark["bg_color"] == [0.10, 0.10, 0.15, 1.0]
    assert dark["ambient"] == [0.20, 0.20, 0.20]
    assert dark["lights"]["key_intensity"] == 5.0
    assert dark["lights"]["fill_intensity"] == 2.5
    assert dark["lights"]["rim_intensity"] == 4.0
    assert dark["floor"] is None


def test_light_studio_has_floor_and_softer_lights():
    light = cp._SCENE_THEMES["light_studio"]
    # Светлый фон: каждая компонента ≥ 0.85
    assert all(c >= 0.85 for c in light["bg_color"][:3])
    # Light theme должна снизить интенсивности — иначе металл пересвечен.
    assert light["lights"]["key_intensity"] < 5.0
    assert light["lights"]["fill_intensity"] < 2.5
    assert light["lights"]["rim_intensity"] < 4.0
    # И иметь конфиг пола.
    assert light["floor"] is not None
    assert "color" in light["floor"]


class _FakeMesh:
    """Минимальный stub trimesh-меша: достаточно атрибута .bounds."""

    def __init__(self, bounds: np.ndarray):
        self.bounds = bounds


def test_build_studio_floor_produces_box_under_partition():
    bounds = np.array([[-1.0, 0.0, -0.025], [1.0, 2.5, 0.025]])
    fake = _FakeMesh(bounds)
    cfg = cp._SCENE_THEMES["light_studio"]["floor"]
    floor = cp._build_studio_floor(fake, cfg)
    assert floor is not None, "floor mesh should be built when bounds present"

    fb = floor.bounds
    # Верх пола должен быть на уровне низа рамы (y=0 в этом тесте) — ±epsilon.
    assert fb[1][1] == pytest.approx(0.0, abs=1e-6)
    # Пол шире/глубже партиции на 2*padding по каждой оси.
    pad = cfg["padding"]
    assert (fb[1][0] - fb[0][0]) == pytest.approx((bounds[1][0] - bounds[0][0]) + 2 * pad, abs=1e-6)
    assert (fb[1][2] - fb[0][2]) == pytest.approx((bounds[1][2] - bounds[0][2]) + 2 * pad, abs=1e-6)


def test_build_studio_floor_returns_none_on_bad_mesh():
    """Если у меша нет bounds — возвращаем None, не падаем."""
    class _Bad:
        @property
        def bounds(self):
            raise RuntimeError("no bounds")

    assert cp._build_studio_floor(_Bad(), cp._SCENE_THEMES["light_studio"]["floor"]) is None

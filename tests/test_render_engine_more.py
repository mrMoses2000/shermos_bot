from pathlib import Path

import pytest

from src.engine import render_engine
from src.models import RenderPartitionAction


def test_render_params_maps_materials_and_mullions():
    params = render_engine._render_params(
        RenderPartitionAction(
            shape="Прямая",
            height=2.5,
            width_a=3,
            glass_type="4",
            frame_color="5",
            door_section=2,
            mullion_positions={"vertical_mullions": [1.0]},
        )
    )

    assert params["frame_color_id"] == "5"
    assert params["glass_type_id"] == "4"
    assert params["door_sections"] == [2]
    assert params["vertical_mullions"] == [1.0]
    assert isinstance(params["frame_color"], list)


def test_collect_render_paths_copies_straight_render(tmp_path):
    straight = tmp_path / "partition_render_hq.png"
    straight.write_bytes(b"png")

    paths = render_engine._collect_render_paths(tmp_path)

    assert set(paths) == {"0deg", "90deg", "180deg", "270deg"}
    assert Path(paths["180deg"]).exists()


def test_collect_render_paths_keeps_existing_angle_files(tmp_path):
    angle = tmp_path / "partition_render_hq_90deg.png"
    angle.write_bytes(b"png")

    paths = render_engine._collect_render_paths(tmp_path)

    assert paths == {"90deg": str(angle.resolve())}


@pytest.mark.asyncio
async def test_render_partition_uses_request_directory(monkeypatch, tmp_path):
    seen = {}

    def fake_sync(_params, output_dir):
        seen["dir"] = output_dir
        return {"0deg": str(output_dir / "x.png")}

    monkeypatch.setattr(render_engine, "_sync_render", fake_sync)
    settings = type("Settings", (), {"renders_dir": str(tmp_path)})

    result = await render_engine.render_partition(
        RenderPartitionAction(shape="Прямая", height=2.5, width_a=3),
        "abc",
        settings,
    )

    assert seen["dir"] == tmp_path / "abc"
    assert result["render_paths"]["0deg"].endswith("x.png")

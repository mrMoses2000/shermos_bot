from pathlib import Path
from types import SimpleNamespace

import pytest

from src.engine import render_engine
from src.models import RenderPartitionAction


@pytest.mark.asyncio
async def test_render_partition_wraps_sync_renderer(monkeypatch, tmp_path):
    def fake_sync(params, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        output = Path(output_dir) / "partition_render_hq_0deg.png"
        output.write_bytes(b"png")
        assert params["frame_color_id"] == "1"
        return {"0deg": str(output)}

    monkeypatch.setattr(render_engine, "_sync_render", fake_sync)
    settings = SimpleNamespace(renders_dir=str(tmp_path))

    result = await render_engine.render_partition(
        RenderPartitionAction(shape="Прямая", height=2.5, width_a=3),
        "request-1",
        settings,
    )

    assert result["render_paths"]["0deg"].endswith("partition_render_hq_0deg.png")

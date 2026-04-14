from pathlib import Path
from types import SimpleNamespace

import pytest

from src.engine import render_engine
from src.models import RenderPartitionAction


@pytest.mark.asyncio
async def test_render_partition_runs_subprocess_and_collects_output(monkeypatch, tmp_path):
    class Process:
        pid = 123
        returncode = 0

        async def communicate(self):
            output_dir = tmp_path / "request-1"
            output = output_dir / "partition_render_hq_0deg.png"
            output.write_bytes(b"png")
            assert '"frame_color_id": "1"' in (output_dir / "_render_params.json").read_text()
            return b"", b""

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(render_engine.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    settings = SimpleNamespace(renders_dir=str(tmp_path))

    result = await render_engine.render_partition(
        RenderPartitionAction(shape="Прямая", height=2.5, width_a=3),
        "request-1",
        settings,
    )

    assert result["render_paths"]["0deg"].endswith("partition_render_hq_0deg.png")

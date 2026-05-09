from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.engine import render_engine
from src.models import RenderPartitionAction


def test_render_partition_action_rejects_unknown_shape():
    # Single-letter / non-canonical values must be rejected at the model boundary
    # so we never reach the renderer with a malformed shape (regression for
    # Gemini emitting shape="Р").
    for bad in ("Р", "P", "П", "u", "П-образная (ниша)"):
        with pytest.raises(ValidationError):
            RenderPartitionAction(shape=bad, height=2.5, width_a=3)
    # Canonical values pass through unchanged.
    for good in ("Прямая", "Г-образная", "П-образная"):
        RenderPartitionAction(shape=good, height=2.5, width_a=3)


def test_render_partition_action_handle_position_is_constrained():
    # The renderer treats handle_position 'Лево' / 'Центр' / 'Право' as the
    # intra-section horizontal placement of the handle. Anything else used to
    # silently fall through to the right-edge default in _create_handle —
    # now it must fail at the model boundary.
    for bad in ("left", "left-side", "посередине", "верх"):
        with pytest.raises(ValidationError):
            RenderPartitionAction(shape="Прямая", height=2.5, width_a=3, handle_position=bad)
    for good in ("Лево", "Центр", "Право"):
        RenderPartitionAction(shape="Прямая", height=2.5, width_a=3, handle_position=good)


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

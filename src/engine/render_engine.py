"""Async wrapper around the synchronous 3D partition renderer."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from src.models import RenderPartitionAction
from src.utils.config_manager import config
from src.utils.query_parser import normalize_render_params


def _render_params(params: RenderPartitionAction) -> dict[str, Any]:
    normalized = normalize_render_params(params.model_dump(exclude_none=True))
    frame_material = config.get_material("frame_colors", normalized["frame_color"])
    glass_material = config.get_material("glass_types", normalized["glass_type"])
    normalized["frame_color_id"] = normalized["frame_color"]
    normalized["glass_type_id"] = normalized["glass_type"]
    normalized["frame_color"] = frame_material["color"] if frame_material else [0.05, 0.05, 0.05, 1.0]
    normalized["glass_color"] = glass_material["color"] if glass_material else [0.85, 0.85, 0.85, 0.3]
    normalized["glass_roughness"] = (glass_material or {}).get("roughness", 0.05)
    if params.door_section:
        normalized["door_sections"] = [params.door_section]
    if params.mullion_positions:
        normalized.update(params.mullion_positions)
    return normalized


def _collect_render_paths(output_dir: Path) -> dict[str, str]:
    angle_files = {
        "0deg": output_dir / "partition_render_hq_0deg.png",
        "90deg": output_dir / "partition_render_hq_90deg.png",
        "180deg": output_dir / "partition_render_hq_180deg.png",
        "270deg": output_dir / "partition_render_hq_270deg.png",
    }
    straight = output_dir / "partition_render_hq.png"
    if straight.exists():
        for angle, path in angle_files.items():
            if angle == "0deg":
                shutil.copyfile(straight, path)
            elif not path.exists():
                shutil.copyfile(straight, path)
    return {angle: str(path.resolve()) for angle, path in angle_files.items() if path.exists()}


def _sync_render(params: dict[str, Any], output_dir: Path) -> dict[str, str]:
    from src.render.create_partition import generate_from_params
    from src.render.validators import validate_partition_params

    valid, errors = validate_partition_params(params)
    if not valid:
        raise ValueError("; ".join(errors))

    output_dir.mkdir(parents=True, exist_ok=True)
    previous_output = os.environ.get("OUTPUT_DIR")
    previous_server_mode = os.environ.pop("SERVER_MODE", None)
    os.environ["OUTPUT_DIR"] = str(output_dir)
    try:
        generate_from_params(params, {"materials": config.get_section("materials")})
    finally:
        if previous_output is None:
            os.environ.pop("OUTPUT_DIR", None)
        else:
            os.environ["OUTPUT_DIR"] = previous_output
        if previous_server_mode is not None:
            os.environ["SERVER_MODE"] = previous_server_mode
    paths = _collect_render_paths(output_dir)
    if not paths:
        raise RuntimeError("Renderer did not produce PNG files")
    return paths


async def render_partition(params: RenderPartitionAction, request_id: str, settings) -> dict[str, Any]:
    render_params = _render_params(params)
    output_dir = Path(settings.renders_dir) / request_id
    loop = asyncio.get_running_loop()
    render_paths = await loop.run_in_executor(None, _sync_render, render_params, output_dir)
    return {"render_paths": render_paths}

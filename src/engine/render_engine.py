"""Async wrapper around the synchronous 3D partition renderer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from src.config import settings as _settings
from src.engine.pricing_cache import pricing_cache
from src.models import RenderPartitionAction
from src.utils.config_manager import config
from src.utils.query_parser import normalize_render_params

logger = logging.getLogger(__name__)

# Default lives in src/config.py (Settings.render_timeout_seconds, default 300).
# Kept here as a module-level fallback so call sites that pass a settings
# object override it cleanly.
_DEFAULT_RENDER_TIMEOUT = 300


def _render_params(params: RenderPartitionAction) -> dict[str, Any]:
    normalized = normalize_render_params(params.model_dump(exclude_none=True))
    pc = pricing_cache
    normalized["frame_color_id"] = normalized["frame_color"]
    normalized["glass_type_id"] = normalized["glass_type"]
    normalized["frame_color"] = pc.get_frame_color(normalized["frame_color"])
    normalized["glass_color"] = pc.get_glass_color(normalized["glass_type"])
    normalized["glass_roughness"] = pc.get_glass_roughness(normalized["glass_type"])
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
    from src.render.validators import validate_partition_params

    valid, errors = validate_partition_params(render_params)
    if not valid:
        raise ValueError("; ".join(errors))

    output_dir = Path(settings.renders_dir) / request_id
    output_dir.mkdir(parents=True, exist_ok=True)
    params_file = output_dir / "_render_params.json"
    params_file.write_text(json.dumps(render_params), encoding="utf-8")
    project_root = Path(__file__).resolve().parents[2]
    script = f"""
import json
import os
import sys

os.environ["OUTPUT_DIR"] = {str(output_dir)!r}
sys.path.insert(0, {str(project_root)!r})

params = json.loads(open({str(params_file)!r}, encoding="utf-8").read())
from src.render.create_partition import generate_from_params
from src.utils.config_manager import config

generate_from_params(params, {{"materials": config.get_section("materials")}})
"""
    timeout = getattr(settings, "render_timeout_seconds", None) or _DEFAULT_RENDER_TIMEOUT

    logger.info(
        "render_started",
        extra={
            "request_id": request_id,
            "shape": render_params.get("shape"),
            "sections": render_params.get("sections"),
            "rows": render_params.get("rows"),
            "cols": render_params.get("cols"),
            "height": render_params.get("height"),
            "width": render_params.get("width"),
            "timeout": timeout,
        },
    )
    started_at = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env={**os.environ, "PYOPENGL_PLATFORM": "egl"},
    )
    try:
        _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started_at
        # Best-effort: drain whatever the renderer wrote so the timeout
        # is debuggable instead of a black box. Keep this short — we are
        # already past budget.
        partial_stderr = b""
        if process.stderr is not None:
            try:
                partial_stderr = await asyncio.wait_for(process.stderr.read(2048), timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                partial_stderr = b""
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        logger.error(
            "render_timeout",
            extra={
                "request_id": request_id,
                "elapsed": round(elapsed, 1),
                "timeout": timeout,
                "stderr_tail": partial_stderr.decode("utf-8", errors="ignore")[-500:],
            },
        )
        raise TimeoutError(f"3D render timed out after {timeout}s (elapsed={elapsed:.1f}s)")

    elapsed = time.monotonic() - started_at
    if process.returncode != 0:
        error_text = stderr.decode("utf-8", errors="ignore")[:500]
        logger.error(
            "render_failed",
            extra={"request_id": request_id, "elapsed": round(elapsed, 1), "stderr_tail": error_text},
        )
        raise RuntimeError(f"Renderer failed: {error_text}")

    params_file.unlink(missing_ok=True)
    render_paths = _collect_render_paths(output_dir)
    if not render_paths:
        logger.error(
            "render_no_output",
            extra={"request_id": request_id, "elapsed": round(elapsed, 1)},
        )
        raise RuntimeError("Renderer did not produce PNG files")
    logger.info(
        "render_finished",
        extra={
            "request_id": request_id,
            "elapsed": round(elapsed, 1),
            "frames": len(render_paths),
        },
    )
    return {"render_paths": render_paths}

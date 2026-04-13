"""Gemini CLI subprocess executor with concurrency and timeout control."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import time
from pathlib import Path

from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
_semaphore: asyncio.Semaphore | None = None
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, min(10, settings.max_llm_concurrency)))
    return _semaphore


def _clean_output(output: str) -> str:
    output = ANSI_RE.sub("", output)
    noise_prefixes = (
        "Loaded cached credentials",
        "Gemini CLI",
        "Using model",
        "Data collection",
    )
    lines = [line for line in output.splitlines() if not line.strip().startswith(noise_prefixes)]
    return "\n".join(lines).strip()


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
    except (ProcessLookupError, asyncio.TimeoutError):
        if process.returncode is None:
            process.kill()
            await process.wait()


async def call_llm(prompt: str) -> str:
    semaphore = _get_semaphore()
    wait_start = time.perf_counter()
    async with semaphore:
        waited = time.perf_counter() - wait_start
        exec_start = time.perf_counter()
        command = [settings.llm_cli_command, *shlex.split(settings.llm_cli_flags), prompt]
        env = os.environ.copy()
        project_root = Path(__file__).resolve().parents[2]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=settings.llm_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            if process.returncode is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            await _terminate_process(process)
            raise TimeoutError("Gemini CLI timed out") from exc

        duration = time.perf_counter() - exec_start
        logger.info(
            "llm_call_finished",
            extra={"t_wait_llm": round(waited, 3), "t_exec_llm": round(duration, 3)},
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"Gemini CLI failed with code {process.returncode}: "
                f"{stderr.decode('utf-8', errors='ignore')}"
            )
        return _clean_output(stdout.decode("utf-8", errors="ignore"))

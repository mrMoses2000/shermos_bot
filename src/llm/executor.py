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
_dotenv_cache: dict[str, str] | None = None
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Keys that Gemini CLI reads from environment / .env
# (GEMINI_API_KEY not needed — using OAuth; tokens in ~/.gemini/)
_GEMINI_ENV_KEYS = ("GEMINI_MODEL",)


def _read_dotenv_gemini_vars() -> dict[str, str]:
    """Read Gemini-relevant vars from project .env file.

    Gemini CLI auto-discovers .env when cwd is the project root,
    but in some deployments (systemd) the cwd may differ. Belt-and-suspenders.
    """
    global _dotenv_cache
    if _dotenv_cache is not None:
        return _dotenv_cache
    result: dict[str, str] = {}
    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if dotenv_path.is_file():
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key in _GEMINI_ENV_KEYS:
                result[key] = value.strip()
    _dotenv_cache = result
    return result


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
        flags = shlex.split(settings.llm_cli_flags) if settings.llm_cli_flags.strip() else []
        # Two modes: if flags contain -p, append prompt as CLI arg.
        # Otherwise, pipe prompt via stdin (no size limit, safer).
        use_stdin = "-p" not in flags and "--prompt" not in flags
        if use_stdin:
            command = [settings.llm_cli_command, *flags]
        else:
            command = [settings.llm_cli_command, *flags, prompt]
        env = os.environ.copy()
        # Gemini CLI reads these env vars; pydantic-settings loads .env
        # into Python objects but NOT into os.environ, so propagate manually.
        _dotenv = _read_dotenv_gemini_vars()
        env.update(_dotenv)
        project_root = Path(__file__).resolve().parents[2]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(project_root),
            stdin=asyncio.subprocess.PIPE if use_stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        try:
            stdin_bytes = prompt.encode("utf-8") if use_stdin else None
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=stdin_bytes),
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

"""Periodic Gemini CLI health check."""

from __future__ import annotations

import asyncio

from src.llm.executor import call_llm
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_HEALTH_PROMPT = 'Respond with exactly: {"reply_text":"ok","actions":null}'
_CHECK_INTERVAL = 600
_gemini_healthy = True


def is_gemini_healthy() -> bool:
    return _gemini_healthy


async def run_gemini_health_check(interval: int = _CHECK_INTERVAL) -> None:
    global _gemini_healthy
    await asyncio.sleep(30)
    while True:
        try:
            result = await call_llm(_HEALTH_PROMPT)
            if "ok" in result.lower():
                if not _gemini_healthy:
                    logger.info("gemini_health_recovered")
                _gemini_healthy = True
            else:
                logger.warning("gemini_health_unexpected_output", extra={"output": result[:200]})
                _gemini_healthy = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _gemini_healthy = False
            logger.critical("gemini_health_check_failed", extra={"error": str(exc)})
        await asyncio.sleep(interval)

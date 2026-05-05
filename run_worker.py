"""Worker process entrypoint."""

import asyncio
import signal

from src.queue.worker import run_worker
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def _main() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal(sig_name: str) -> None:
        logger.info("worker_shutdown_initiated", extra={"signal": sig_name})
        stop_event.set()

    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name)
        try:
            loop.add_signal_handler(sig, _on_signal, sig_name)
        except NotImplementedError:
            # Windows doesn't support SIGTERM via add_signal_handler
            pass

    main_task = asyncio.create_task(run_worker())
    stop_task = asyncio.create_task(stop_event.wait())
    done, _pending = await asyncio.wait(
        {main_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stop_task in done:
        main_task.cancel()
        try:
            await main_task
        except asyncio.CancelledError:
            pass
    logger.info("worker_shutdown_complete")


if __name__ == "__main__":
    asyncio.run(_main())

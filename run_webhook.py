"""aiohttp webhook process entrypoint."""

from __future__ import annotations

import asyncio
import signal
import ssl

from aiohttp import web

from src.bot.telegram_sender import telegram_sender
from src.bot.webhook import setup_routes
from src.config import settings
from src.db import postgres
from src.db.redis_client import RedisClient
from src.utils.logger import setup_logger
from src.utils.watchdog import notify_ready, notify_stopping, run_watchdog_loop

logger = setup_logger(__name__)


async def _app_context(app: web.Application):
    pg_pool = await postgres.create_pool(settings)
    await postgres.run_migrations(pg_pool)
    await postgres.seed_default_prices(pg_pool)
    await postgres.seed_default_materials(pg_pool)
    redis_client = RedisClient(settings.redis_url)
    await redis_client.connect()
    await telegram_sender.start()
    app["pg_pool"] = pg_pool
    app["redis"] = redis_client
    yield
    await telegram_sender.close()
    await redis_client.close()
    await postgres.close_pool(pg_pool)


def create_app() -> web.Application:
    app = web.Application()
    app.cleanup_ctx.append(_app_context)
    setup_routes(app)
    return app


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(settings.ssl_cert_path, settings.ssl_key_path)
    return context


async def main() -> None:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=settings.webhook_host,
        port=settings.webhook_port,
        ssl_context=_ssl_context(),
    )
    await site.start()
    logger.info(
        "webhook_server_started",
        extra={"host": settings.webhook_host, "port": settings.webhook_port},
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal(sig_name: str) -> None:
        logger.info("webhook_shutdown_initiated", extra={"signal": sig_name})
        stop_event.set()

    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name)
        try:
            loop.add_signal_handler(sig, _on_signal, sig_name)
        except NotImplementedError:
            # Windows doesn't support SIGTERM via add_signal_handler
            pass

    notify_ready()
    watchdog_task = asyncio.create_task(run_watchdog_loop(30))
    await stop_event.wait()
    notify_stopping()
    watchdog_task.cancel()
    logger.info("webhook_shutdown_complete")
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

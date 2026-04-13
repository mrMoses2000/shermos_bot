"""aiohttp webhook process entrypoint."""

from __future__ import annotations

import asyncio
import ssl

from aiohttp import web

from src.bot.telegram_sender import telegram_sender
from src.bot.webhook import setup_routes
from src.config import settings
from src.db import postgres
from src.db.redis_client import RedisClient


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
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

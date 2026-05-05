"""FastAPI sub-application for Telegram Mini App REST API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from src.api import (
    routes_analytics,
    routes_auth,
    routes_clients,
    routes_gallery,
    routes_health,
    routes_measurements,
    routes_orders,
    routes_pricing,
    routes_settings,
    routes_whatsapp,
)
from src.config import settings
from src.db import postgres
from src.utils.metrics import render_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "pg_pool"):
        app.state.pg_pool = await postgres.create_pool(settings)
        app.state.owns_pool = True
        await postgres.run_migrations(app.state.pg_pool)
        await postgres.seed_default_prices(app.state.pg_pool)
        await postgres.seed_default_materials(app.state.pg_pool)
    else:
        app.state.owns_pool = False
    yield
    redis_client = getattr(app.state, "redis_client", None)
    if redis_client is not None:
        await redis_client.close()
    if getattr(app.state, "owns_pool", False):
        await postgres.close_pool(app.state.pg_pool)


def create_app() -> FastAPI:
    app = FastAPI(title="Shermos Mini App API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "X-Telegram-Init-Data",
            "X-CMS-Admin-Token",
            "X-CSRF-Token",
            "Content-Type",
        ],
    )
    app.include_router(routes_auth.router)
    app.include_router(routes_orders.router)
    app.include_router(routes_clients.router)
    app.include_router(routes_measurements.router)
    app.include_router(routes_pricing.router)
    app.include_router(routes_gallery.router)
    app.include_router(routes_analytics.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_whatsapp.router)
    app.include_router(routes_health.router)

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "shermos-mini-api"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    return app


app = create_app()

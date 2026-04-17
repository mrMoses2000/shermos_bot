"""FastAPI sub-application for Telegram Mini App REST API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import (
    routes_analytics,
    routes_clients,
    routes_gallery,
    routes_measurements,
    routes_orders,
    routes_pricing,
    routes_settings,
)
from src.config import settings
from src.db import postgres


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
    if getattr(app.state, "owns_pool", False):
        await postgres.close_pool(app.state.pg_pool)


def create_app() -> FastAPI:
    app = FastAPI(title="Shermos Mini App API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_orders.router)
    app.include_router(routes_clients.router)
    app.include_router(routes_measurements.router)
    app.include_router(routes_pricing.router)
    app.include_router(routes_gallery.router)
    app.include_router(routes_analytics.router)
    app.include_router(routes_settings.router)

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "shermos-mini-api"}

    return app


app = create_app()

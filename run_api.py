"""Uvicorn entrypoint for Mini App API + SPA static files."""

from __future__ import annotations

import uvicorn
from fastapi.staticfiles import StaticFiles

from src.api.app import app
from src.config import settings

# Serve built mini-app SPA — catch-all for non-API routes
app.mount("/", StaticFiles(directory="mini-app/dist", html=True), name="spa")

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9443,
        ssl_certfile=settings.ssl_cert_path,
        ssl_keyfile=settings.ssl_key_path,
        log_level="info",
    )

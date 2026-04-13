"""Uvicorn entrypoint for Mini App API + SPA static files."""

from __future__ import annotations

import ssl

import uvicorn
from fastapi.staticfiles import StaticFiles

from src.api.app import app
from src.config import settings

# Serve built mini-app SPA — catch-all for non-API routes
app.mount("/", StaticFiles(directory="mini-app/dist", html=True), name="spa")

if __name__ == "__main__":
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(settings.ssl_cert_path, settings.ssl_key_path)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8443,
        ssl=ssl_ctx,
        log_level="info",
    )

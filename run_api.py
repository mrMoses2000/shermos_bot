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
        host="127.0.0.1",
        port=9443,
        log_level="info",
    )

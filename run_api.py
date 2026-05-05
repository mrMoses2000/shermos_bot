"""Uvicorn entrypoint for Mini App API + (optionally) SPA static files.

Production: frontend is deployed to Netlify, this process serves API only.
Local dev: set SERVE_FRONTEND_LOCAL=1 to also mount mini-app/dist on /.
"""

from __future__ import annotations

import os

import uvicorn
from fastapi.staticfiles import StaticFiles

from src.api.app import app
from src.config import settings

os.makedirs(settings.gallery_dir, exist_ok=True)
app.mount("/gallery", StaticFiles(directory=settings.gallery_dir, check_dir=False), name="gallery")

# Phase 6.7: SPA static is served by Netlify in production.
# Mount locally only when SERVE_FRONTEND_LOCAL=1 is explicitly set (dev convenience).
if os.getenv("SERVE_FRONTEND_LOCAL") == "1":
    app.mount("/", StaticFiles(directory="mini-app/dist", html=True), name="spa")

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=9443,
        log_level="info",
    )

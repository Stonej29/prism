"""FastAPI application factory.

All routes live under /api on a single app (so `app.dependency_overrides`
works in tests); if a built frontend bundle is present it is served as a
single-page app at / (mounted last so /api/* always wins).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from prism.web.routes import activity, files, graph, ideas, maintenance, notes, profile, proposals, search, stats, tags, tree


def _static_dir() -> Path | None:
    candidates = []
    env = os.getenv("PRISM_WEB_STATIC", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.append(Path("/app/static"))
    candidates.append(Path(__file__).resolve().parents[3] / "frontend" / "dist")
    for path in candidates:
        if path.is_dir() and (path / "index.html").exists():
            return path
    return None


def create_app() -> FastAPI:
    app = FastAPI(title="PRISM", version="0.1.0")

    api = APIRouter(prefix="/api")
    for module in (notes, graph, tags, stats, search, ideas, proposals, maintenance, tree, files, activity, profile):
        api.include_router(module.router)
    app.include_router(api)

    static = _static_dir()
    if static is not None:
        app.mount("/", StaticFiles(directory=str(static), html=True), name="ui")

    return app

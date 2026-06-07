"""FastAPI application factory.

All routes live under /api on a single app (so `app.dependency_overrides`
works in tests); if a built frontend bundle is present it is served as a
single-page app at / (mounted last so /api/* always wins).
"""
from __future__ import annotations

import base64
import binascii
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from prism.web.routes import activity, files, graph, ideas, maintenance, notes, profile, proposals, search, stats, tags, tree


def _basic_auth_credentials() -> tuple[str, str] | None:
    username = os.getenv("PRISM_WEB_USERNAME", "").strip()
    password = os.getenv("PRISM_WEB_PASSWORD", "")
    if not username and not password:
        return None
    if not username or not password:
        raise RuntimeError("PRISM_WEB_USERNAME and PRISM_WEB_PASSWORD must be set together.")
    return username, password


def _is_authorized(auth_header: str | None, credentials: tuple[str, str]) -> bool:
    if not auth_header:
        return False
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, sep, password = decoded.partition(":")
    if sep != ":":
        return False
    expected_username, expected_password = credentials
    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(password, expected_password)


def _auth_challenge() -> Response:
    return Response(
        "Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="PRISM"'},
    )


def _install_basic_auth(app: FastAPI, credentials: tuple[str, str] | None) -> None:
    if credentials is None:
        return

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not _is_authorized(request.headers.get("authorization"), credentials):
            return _auth_challenge()
        return await call_next(request)


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
    _install_basic_auth(app, _basic_auth_credentials())

    api = APIRouter(prefix="/api")
    for module in (notes, graph, tags, stats, search, ideas, proposals, maintenance, tree, files, activity, profile):
        api.include_router(module.router)
    app.include_router(api)

    static = _static_dir()
    if static is not None:
        app.mount("/", StaticFiles(directory=str(static), html=True), name="ui")

    return app

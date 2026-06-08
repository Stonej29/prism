"""FastAPI application factory.

All routes live under /api on a single app (so `app.dependency_overrides`
works in tests); if a built frontend bundle is present it is served as a
single-page app at / (mounted last so /api/* always wins).
"""
from __future__ import annotations

import ipaddress
import logging
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from prism.web import auth
from prism.web.routes import activity, files, graph, ideas, maintenance, notes, profile, proposals, search, settings, stats, tags, tree
from prism.web.routes import auth as auth_routes

logger = logging.getLogger(__name__)

# Auth-status is always reachable so the SPA can decide what screen to show.
# The static shell (non-/api paths) is always public — it carries no vault data.
_STATUS_PATH = "/api/auth/status"


def _is_loopback_host(host: str) -> bool:
    host = host.strip().strip("[]")
    if host in {"", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A non-literal hostname we can't classify; treat as non-loopback so the
        # auth guard errs on the safe side.
        return False


def _auth_enforced(authenticator: auth.Authenticator) -> bool:
    """Enforce auth when an account exists, or when bound to a LAN interface.

    Loopback with no account stays open (local-dev convenience); a LAN-exposed
    bind with no account enters first-run setup mode instead of serving openly.
    """
    if authenticator.is_configured():
        return True
    host = os.getenv("PRISM_WEB_HOST", "127.0.0.1")
    return not _is_loopback_host(host)


def _install_auth(app: FastAPI, authenticator: auth.Authenticator) -> None:
    @app.middleware("http")
    async def gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        # Static SPA shell and the status probe stay public so the browser can
        # load and decide between the setup / login / vault screens.
        if not path.startswith("/api/") or path == _STATUS_PATH:
            return await call_next(request)
        if authenticator.needs_setup():
            # First run: only the create-account endpoint is reachable.
            if path == "/api/auth/setup":
                return await call_next(request)
            return JSONResponse({"detail": "Account setup required"}, status_code=401)
        # Configured: login/logout are public; setup is closed; the rest needs auth.
        if path in {"/api/auth/login", "/api/auth/logout"}:
            return await call_next(request)
        if path == "/api/auth/setup":
            return JSONResponse({"detail": "An account already exists."}, status_code=409)
        if authenticator.authenticated(request.cookies.get(auth.COOKIE_NAME), request.headers.get("authorization")):
            return await call_next(request)
        return JSONResponse({"detail": "Authentication required"}, status_code=401)


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
    authenticator = auth.Authenticator.from_env()
    enforced = _auth_enforced(authenticator)
    app.state.authenticator = authenticator
    app.state.auth_enforced = enforced
    if enforced:
        if authenticator.needs_setup():
            logger.warning(
                "PRISM web UI is exposed without an account; the first browser to reach it "
                "can create the owner login. Set PRISM_WEB_USERNAME/PRISM_WEB_PASSWORD to "
                "pin credentials, or keep it on a trusted network."
            )
        _install_auth(app, authenticator)

    api = APIRouter(prefix="/api")
    for module in (notes, graph, tags, stats, search, ideas, proposals, maintenance, tree, files, activity, profile, settings, auth_routes):
        api.include_router(module.router)
    app.include_router(api)

    static = _static_dir()
    if static is not None:
        app.mount("/", StaticFiles(directory=str(static), html=True), name="ui")

    return app

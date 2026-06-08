from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from prism.web import auth
from prism.web.schemas import ChangePasswordBody, LoginBody, SetupBody

router = APIRouter(prefix="/auth", tags=["auth"])


def _authenticator(request: Request) -> auth.Authenticator:
    return request.app.state.authenticator


def _enforced(request: Request) -> bool:
    return bool(getattr(request.app.state, "auth_enforced", False))


def _set_session(response: Response, authenticator: auth.Authenticator) -> None:
    response.set_cookie(
        auth.COOKIE_NAME,
        authenticator.issue_session(),
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure(),
        path="/",
    )


@router.get("/status")
def auth_status(request: Request) -> dict:
    if not _enforced(request):
        return {"auth_required": False, "authenticated": True, "needs_setup": False, "env_locked": False}
    a = _authenticator(request)
    return {
        "auth_required": True,
        "authenticated": a.authenticated(
            request.cookies.get(auth.COOKIE_NAME), request.headers.get("authorization")
        ),
        "needs_setup": a.needs_setup(),
        "env_locked": a.env_locked,
    }


@router.post("/setup")
def setup_account(body: SetupBody, request: Request, response: Response) -> dict:
    if not _enforced(request):
        return {"ok": True, "authenticated": True}
    a = _authenticator(request)
    if a.env_locked:
        raise HTTPException(status_code=409, detail="Credentials are set via environment variables.")
    if not a.needs_setup():
        raise HTTPException(status_code=409, detail="An account already exists.")
    try:
        a.create_account(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_session(response, a)  # auto-login the new account
    return {"ok": True, "authenticated": True}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    if not _enforced(request):
        return {"ok": True, "authenticated": True}
    a = _authenticator(request)
    if not a.verify_password(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    _set_session(response, a)
    return {"ok": True, "authenticated": True}


@router.post("/change-password")
def change_password(body: ChangePasswordBody, request: Request, response: Response) -> dict:
    if not _enforced(request):
        raise HTTPException(status_code=409, detail="Authentication is not enabled.")
    a = _authenticator(request)
    try:
        a.change_password(body.current_password, body.new_password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _set_session(response, a)  # re-issue so the current session survives the secret rotation
    return {"ok": True, "authenticated": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True, "authenticated": False}

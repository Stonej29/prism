"""Web UI authentication.

Single owner account. The credential can come from two places, in order of
precedence:

1. ``PRISM_WEB_USERNAME`` / ``PRISM_WEB_PASSWORD`` env vars — when set, they lock
   the account (no UI changes) and no on-disk store is used.
2. An on-disk store (``PRISM_WEB_AUTH_FILE``, default ``<sqlite dir>/web-auth.json``)
   written by the first-run "create account" flow in the UI. The password is kept
   as a PBKDF2-SHA256 hash, never in plaintext.

When neither exists the account is *unconfigured*: on a LAN-exposed bind the UI
shows a one-time "create your account" screen; on loopback the UI is simply open
(local-dev convenience). Login state is carried by an HMAC-signed session cookie.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

Credentials = tuple[str, str]

COOKIE_NAME = "prism_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
MIN_PASSWORD_LENGTH = 8

_PBKDF2_ITERATIONS = 210_000
_SALT_BYTES = 16


def env_credentials() -> Credentials | None:
    """Owner credential pinned via env vars, or ``None``.

    Raises if exactly one of username/password is set (a misconfiguration that
    would otherwise silently disable auth).
    """
    username = os.getenv("PRISM_WEB_USERNAME", "").strip()
    password = os.getenv("PRISM_WEB_PASSWORD", "")
    if not username and not password:
        return None
    if not username or not password:
        raise RuntimeError("PRISM_WEB_USERNAME and PRISM_WEB_PASSWORD must be set together.")
    return username, password


def auth_file() -> Path:
    explicit = os.getenv("PRISM_WEB_AUTH_FILE", "").strip()
    if explicit:
        return Path(explicit)
    sqlite_path = Path(os.getenv("SQLITE_PATH", "/data/prism.sqlite3"))
    return sqlite_path.parent / "web-auth.json"


def cookie_secure() -> bool:
    """Whether to set ``Secure`` on the session cookie.

    Off by default so the cookie works over plain HTTP on a trusted LAN. Set
    ``PRISM_WEB_COOKIE_SECURE=1`` when serving behind HTTPS / a TLS proxy.
    """
    return os.getenv("PRISM_WEB_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}


def _hash_password(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


class Authenticator:
    """Resolves, persists, and verifies the single owner credential."""

    def __init__(self, env: Credentials | None, store_path: Path) -> None:
        self._env = env
        self._store_path = store_path
        self._cache: dict | None = None
        self._cache_key: tuple[int, int] | None = None

    @classmethod
    def from_env(cls) -> "Authenticator":
        return cls(env_credentials(), auth_file())

    # --- on-disk store -------------------------------------------------
    def _load(self) -> dict | None:
        if self._env is not None:
            return None
        try:
            stat = self._store_path.stat()
        except FileNotFoundError:
            self._cache = self._cache_key = None
            return None
        except OSError:
            return None
        key = (stat.st_mtime_ns, stat.st_size)
        if key == self._cache_key:
            return self._cache
        try:
            data = json.loads(self._store_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not (isinstance(data, dict) and {"username", "salt", "hash"} <= data.keys()):
            data = None
        self._cache_key, self._cache = key, data
        return data

    # --- state ---------------------------------------------------------
    @property
    def env_locked(self) -> bool:
        return self._env is not None

    def is_configured(self) -> bool:
        return self._env is not None or self._load() is not None

    def needs_setup(self) -> bool:
        return not self.is_configured()

    # --- first-run setup ----------------------------------------------
    def create_account(self, username: str, password: str) -> None:
        if self.env_locked:
            raise RuntimeError("Credentials are configured via environment variables.")
        if self.is_configured():
            raise RuntimeError("An account already exists.")
        username = username.strip()
        if not username:
            raise ValueError("Username is required.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        self._write_account(username, password)

    def change_password(self, current_password: str, new_password: str) -> None:
        if self.env_locked:
            raise RuntimeError("Credentials are configured via environment variables.")
        stored = self._load()
        if stored is None:
            raise RuntimeError("No account to update.")
        username = str(stored.get("username", ""))
        if not self.verify_password(username, current_password):
            raise PermissionError("Current password is incorrect.")
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        self._write_account(username, new_password)

    def _write_account(self, username: str, password: str) -> None:
        salt = secrets.token_bytes(_SALT_BYTES)
        payload = {
            "algo": "pbkdf2_sha256",
            "username": username,
            "salt": salt.hex(),
            "iterations": _PBKDF2_ITERATIONS,
            "hash": _hash_password(password, salt, _PBKDF2_ITERATIONS).hex(),
        }
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._store_path.with_name(self._store_path.name + ".tmp")
        tmp.write_text(json.dumps(payload), "utf-8")
        os.replace(tmp, self._store_path)
        try:
            os.chmod(self._store_path, 0o600)
        except OSError:
            pass
        self._cache = self._cache_key = None

    # --- verification --------------------------------------------------
    def verify_password(self, username: str, password: str) -> bool:
        if self._env is not None:
            exp_u, exp_p = self._env
            return secrets.compare_digest(username, exp_u) and secrets.compare_digest(password, exp_p)
        stored = self._load()
        if stored is None:
            return False
        try:
            salt = bytes.fromhex(stored["salt"])
            expected = bytes.fromhex(stored["hash"])
            iterations = int(stored.get("iterations", _PBKDF2_ITERATIONS))
        except (ValueError, TypeError):
            return False
        candidate = _hash_password(password, salt, iterations)
        user_ok = secrets.compare_digest(username, str(stored.get("username", "")))
        return user_ok and hmac.compare_digest(candidate, expected)

    # --- session cookie -----------------------------------------------
    def _secret(self) -> bytes:
        override = os.getenv("PRISM_WEB_SESSION_SECRET", "").strip()
        if override:
            return override.encode("utf-8")
        if self._env is not None:
            u, p = self._env
            return hashlib.sha256(f"{u}:{p}".encode("utf-8")).digest()
        stored = self._load()
        if stored is not None:
            return hashlib.sha256(f"{stored.get('username')}:{stored.get('hash')}".encode("utf-8")).digest()
        return b""  # unconfigured: no valid sessions exist

    def _sign(self, payload: str) -> str:
        mac = hmac.new(self._secret(), payload.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode("ascii")

    def issue_session(self) -> str:
        payload = base64.urlsafe_b64encode(str(int(time.time())).encode("ascii")).decode("ascii")
        return f"{payload}.{self._sign(payload)}"

    def verify_session(self, token: str | None) -> bool:
        if not token or not self.is_configured():
            return False
        if not self._secret():
            return False
        payload, sep, signature = token.partition(".")
        if not sep or not hmac.compare_digest(signature, self._sign(payload)):
            return False
        try:
            issued_at = int(base64.urlsafe_b64decode(payload.encode("ascii")).decode("ascii"))
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return False
        return 0 <= (time.time() - issued_at) <= SESSION_TTL_SECONDS

    def verify_basic(self, auth_header: str | None) -> bool:
        """Accept ``Authorization: Basic`` for curl/CLI access."""
        if not auth_header or not self.is_configured():
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
        return self.verify_password(username, password)

    def authenticated(self, cookie: str | None, auth_header: str | None) -> bool:
        return self.verify_session(cookie) or self.verify_basic(auth_header)

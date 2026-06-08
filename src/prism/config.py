from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from prism.settings_store import load_overrides, merged

DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"

DEFAULT_VAULT_PATH = Path("/data/research-vault")
DEFAULT_SQLITE_PATH = Path("/data/prism.sqlite3")
DEFAULT_ARCHIVE_PATH = Path("/data/archives")
DEFAULT_LANCEDB_PATH = Path("/data/lancedb")

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 5890
DEFAULT_WEB_RELOAD = False
DEFAULT_WEB_COOKIE_SECURE = False

DEFAULT_FETCH_ALLOW_PRIVATE = False
DEFAULT_FETCH_USE_JINA_READER = True
DEFAULT_FETCH_TIMEOUT_SECONDS = 45.0
DEFAULT_FETCH_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
DEFAULT_FETCH_RETRY_ATTEMPTS = 3
DEFAULT_FETCH_RETRY_BACKOFF_BASE = 1.0
DEFAULT_FETCH_MAX_REDIRECTS = 10

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class WebSettings:
    host: str = DEFAULT_WEB_HOST
    port: int = DEFAULT_WEB_PORT
    reload: bool = DEFAULT_WEB_RELOAD
    static_path: Path | None = None
    cookie_secure: bool = DEFAULT_WEB_COOKIE_SECURE


@dataclass(frozen=True)
class FetchSettings:
    allow_private: bool = DEFAULT_FETCH_ALLOW_PRIVATE
    use_jina_reader: bool = DEFAULT_FETCH_USE_JINA_READER
    timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS
    max_download_bytes: int = DEFAULT_FETCH_MAX_DOWNLOAD_BYTES
    retry_attempts: int = DEFAULT_FETCH_RETRY_ATTEMPTS
    retry_backoff_base: float = DEFAULT_FETCH_RETRY_BACKOFF_BASE
    max_redirects: int = DEFAULT_FETCH_MAX_REDIRECTS


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_ids: frozenset[int]
    llm_base_url: str
    llm_api_key: str | None
    llm_model: str | None
    embedding_base_url: str
    embedding_api_key: str | None
    embedding_model: str | None
    vault_path: Path
    sqlite_path: Path
    archive_path: Path
    lancedb_path: Path
    web: WebSettings = field(default_factory=WebSettings)
    fetch: FetchSettings = field(default_factory=FetchSettings)


def load_settings(*, require_telegram: bool = True) -> Settings:
    # env wins, then UI-set overrides in runtime/settings.json, then defaults.
    overrides = load_overrides()

    token = (merged("telegram_bot_token", overrides, "") or "").strip()
    if require_telegram and not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required. Copy .env.example to .env and set it.")

    allowed_user_ids = _parse_allowed_user_ids(merged("telegram_allowed_user_ids", overrides, "") or "")
    if require_telegram and not allowed_user_ids:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS is required. Use comma-separated numeric Telegram user IDs.")

    return Settings(
        telegram_bot_token=token,
        telegram_allowed_user_ids=frozenset(allowed_user_ids),
        llm_base_url=merged("llm_base_url", overrides, DEFAULT_LLM_BASE_URL),
        llm_api_key=merged("llm_api_key", overrides),
        llm_model=merged("llm_model", overrides),
        embedding_base_url=merged("embedding_base_url", overrides, DEFAULT_EMBEDDING_BASE_URL),
        embedding_api_key=merged("embedding_api_key", overrides),
        embedding_model=merged("embedding_model", overrides),
        vault_path=_path_env("VAULT_PATH", DEFAULT_VAULT_PATH),
        sqlite_path=_path_env("SQLITE_PATH", DEFAULT_SQLITE_PATH),
        archive_path=_path_env("ARCHIVE_PATH", DEFAULT_ARCHIVE_PATH),
        lancedb_path=_path_env("LANCEDB_PATH", DEFAULT_LANCEDB_PATH),
        web=load_web_settings(),
        fetch=load_fetch_settings(),
    )


def load_web_settings() -> WebSettings:
    static = os.getenv("PRISM_WEB_STATIC", "").strip()
    return WebSettings(
        host=_str_env("PRISM_WEB_HOST", DEFAULT_WEB_HOST),
        port=_int_env("PRISM_WEB_PORT", DEFAULT_WEB_PORT, 1, 65535),
        reload=_bool_env("PRISM_WEB_RELOAD", DEFAULT_WEB_RELOAD),
        static_path=Path(static) if static else None,
        cookie_secure=_bool_env("PRISM_WEB_COOKIE_SECURE", DEFAULT_WEB_COOKIE_SECURE),
    )


def load_fetch_settings() -> FetchSettings:
    return FetchSettings(
        allow_private=_bool_env("PRISM_FETCH_ALLOW_PRIVATE", DEFAULT_FETCH_ALLOW_PRIVATE),
        use_jina_reader=_bool_env("PRISM_FETCH_USE_JINA_READER", DEFAULT_FETCH_USE_JINA_READER),
        timeout_seconds=_float_env("PRISM_FETCH_TIMEOUT_SECONDS", DEFAULT_FETCH_TIMEOUT_SECONDS, 0.1, 600.0),
        max_download_bytes=_int_env(
            "PRISM_FETCH_MAX_DOWNLOAD_BYTES", DEFAULT_FETCH_MAX_DOWNLOAD_BYTES, 1, 1024 * 1024 * 1024
        ),
        retry_attempts=_int_env("PRISM_FETCH_RETRY_ATTEMPTS", DEFAULT_FETCH_RETRY_ATTEMPTS, 1, 10),
        retry_backoff_base=_float_env("PRISM_FETCH_RETRY_BACKOFF_BASE", DEFAULT_FETCH_RETRY_BACKOFF_BASE, 0.0, 60.0),
        max_redirects=_int_env("PRISM_FETCH_MAX_REDIRECTS", DEFAULT_FETCH_MAX_REDIRECTS, 0, 50),
    )


def _parse_allowed_user_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError as exc:
            raise RuntimeError(f"TELEGRAM_ALLOWED_USER_IDS contains a non-numeric ID: {item!r}") from exc
    return ids


def _str_env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _path_env(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value) if value else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    return min(hi, max(lo, value))


def _float_env(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(os.getenv(name, "").strip())
    except ValueError:
        return default
    return min(hi, max(lo, value))

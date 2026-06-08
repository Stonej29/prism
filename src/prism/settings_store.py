"""Runtime config overrides editable from the web UI.

Values entered in the web Settings panel are written here (a JSON file in the
shared ``runtime/`` volume) and merged over the built-in defaults by
``config.load_settings()``, so every entry point (bot, web, worker, CLI, TUI)
picks them up. **Environment variables always win over the store**, so an
operator-set env value both takes effect and *locks* the corresponding UI field.

Secrets (API keys, the bot token) are stored reversibly — they must be replayed
to the provider, so they can't be hashed. The file is written ``0600`` inside the
already-private ``runtime/`` volume and is never echoed back to the browser.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Override key -> the environment variable that takes precedence over it.
ENV_FOR_KEY: dict[str, str] = {
    "llm_base_url": "LLM_BASE_URL",
    "llm_api_key": "LLM_API_KEY",
    "llm_model": "LLM_MODEL",
    "embedding_base_url": "EMBEDDING_BASE_URL",
    "embedding_api_key": "EMBEDDING_API_KEY",
    "embedding_model": "EMBEDDING_MODEL",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_allowed_user_ids": "TELEGRAM_ALLOWED_USER_IDS",
}

# Keys whose values must never be returned to a client.
SECRET_KEYS = frozenset({"llm_api_key", "embedding_api_key", "telegram_bot_token"})


def config_store_path() -> Path:
    explicit = os.getenv("PRISM_CONFIG_FILE", "").strip()
    if explicit:
        return Path(explicit)
    sqlite_path = Path(os.getenv("SQLITE_PATH", "/data/prism.sqlite3"))
    return sqlite_path.parent / "settings.json"


def load_overrides() -> dict[str, str]:
    """Read stored overrides, tolerant of a missing/malformed file."""
    try:
        raw = json.loads(config_store_path().read_text("utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if key in ENV_FOR_KEY and isinstance(value, str) and value != ""
    }


def save_overrides(updates: dict[str, str | None]) -> dict[str, str]:
    """Merge ``updates`` into the stored overrides and persist atomically.

    A value of ``""`` or ``None`` clears that key; unknown keys are ignored.
    Returns the resulting stored dict (secrets included — callers must not echo).
    """
    current = load_overrides()
    for key, value in updates.items():
        if key not in ENV_FOR_KEY:
            continue
        if value is None or value == "":
            current.pop(key, None)
        else:
            current[key] = value.strip()
    path = config_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(current, indent=2), "utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return current


def env_value(key: str) -> str | None:
    name = ENV_FOR_KEY.get(key)
    if not name:
        return None
    return os.getenv(name, "").strip() or None


def is_env_locked(key: str) -> bool:
    """True when an env var pins this field (UI must show it read-only)."""
    return env_value(key) is not None


def merged(key: str, overrides: dict[str, str], default: str | None = None) -> str | None:
    """Resolve a single field: env wins, then the store, then ``default``."""
    env = env_value(key)
    if env is not None:
        return env
    value = overrides.get(key)
    if value:
        return value.strip()
    return default


def field_source(key: str) -> str:
    """Where the effective value comes from: ``env`` | ``store`` | ``unset``."""
    if env_value(key) is not None:
        return "env"
    if load_overrides().get(key):
        return "store"
    return "unset"

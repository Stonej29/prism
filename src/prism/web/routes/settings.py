"""UI-editable configuration (LLM/embedding/Telegram connection settings).

Values are persisted to the runtime config store (`prism.settings_store`) and
merged over defaults by `config.load_settings()`. Env vars win and *lock* a
field. Secrets are never returned to the client — only whether they're set.

Saving clears the web process's cached `Services` so the next request rebuilds
with the new config (no restart). Separate processes (bot/worker) apply changes
on their next restart.
"""
from __future__ import annotations

from fastapi import APIRouter

from prism.config import DEFAULT_EMBEDDING_BASE_URL, DEFAULT_LLM_BASE_URL
from prism import settings_store as cfg
from prism.web.activity import log_activity
from prism.web.deps import get_services
from prism.web.schemas import SettingsBody

router = APIRouter(prefix="/settings", tags=["settings"])

_DEFAULT_BASE_URLS = {
    "llm_base_url": DEFAULT_LLM_BASE_URL,
    "embedding_base_url": DEFAULT_EMBEDDING_BASE_URL,
}


def _plain(key: str, overrides: dict[str, str]) -> dict:
    return {
        "value": cfg.merged(key, overrides, _DEFAULT_BASE_URLS.get(key)) or "",
        "source": cfg.field_source(key),
        "locked": cfg.is_env_locked(key),
    }


def _secret(key: str, overrides: dict[str, str]) -> dict:
    return {
        "configured": cfg.merged(key, overrides) is not None,
        "source": cfg.field_source(key),
        "locked": cfg.is_env_locked(key),
    }


def _connections_view() -> dict:
    o = cfg.load_overrides()
    llm_ready = bool(cfg.merged("llm_api_key", o) and cfg.merged("llm_model", o))
    emb_ready = bool(cfg.merged("embedding_api_key", o) and cfg.merged("embedding_model", o))
    tg_ready = bool(cfg.merged("telegram_bot_token", o) and cfg.merged("telegram_allowed_user_ids", o))
    return {
        "llm": {
            "configured": llm_ready,
            "base_url": _plain("llm_base_url", o),
            "model": _plain("llm_model", o),
            "api_key": _secret("llm_api_key", o),
        },
        "embedding": {
            "configured": emb_ready,
            "base_url": _plain("embedding_base_url", o),
            "model": _plain("embedding_model", o),
            "api_key": _secret("embedding_api_key", o),
        },
        "telegram": {
            "configured": tg_ready,
            "allowed_user_ids": _plain("telegram_allowed_user_ids", o),
            "bot_token": _secret("telegram_bot_token", o),
            # The bot is a separate process: it applies token/user-id changes on
            # its next restart, unlike the hot-reloaded LLM/embedding settings.
            "applies_on_restart": True,
        },
    }


@router.get("")
def get_settings_config() -> dict:
    return _connections_view()


@router.put("")
def update_settings_config(body: SettingsBody) -> dict:
    # Only forward fields the caller actually provided (None == leave unchanged),
    # and never let a UI write override an env-locked field (env wins anyway).
    updates = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None and not cfg.is_env_locked(key)
    }
    if updates:
        cfg.save_overrides(updates)
        # Rebuild Services on the next request with the new config.
        get_services.cache_clear()
        changed = ", ".join(sorted(k for k in updates if k not in cfg.SECRET_KEYS)) or "credentials"
        log_activity("settings", "ok", f"Updated config ({changed})")
    return _connections_view()

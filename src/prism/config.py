from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from prism.settings_store import load_overrides, merged


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
        llm_base_url=merged("llm_base_url", overrides, "https://openrouter.ai/api/v1"),
        llm_api_key=merged("llm_api_key", overrides),
        llm_model=merged("llm_model", overrides),
        embedding_base_url=merged("embedding_base_url", overrides, "https://api.openai.com/v1"),
        embedding_api_key=merged("embedding_api_key", overrides),
        embedding_model=merged("embedding_model", overrides),
        vault_path=Path(os.getenv("VAULT_PATH", "/data/research-vault")),
        sqlite_path=Path(os.getenv("SQLITE_PATH", "/data/prism.sqlite3")),
        archive_path=Path(os.getenv("ARCHIVE_PATH", "/data/archives")),
        lancedb_path=Path(os.getenv("LANCEDB_PATH", "/data/lancedb")),
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

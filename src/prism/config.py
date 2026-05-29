from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_ids: frozenset[int]
    llm_base_url: str
    llm_api_key: str | None
    llm_model: str | None
    vault_path: Path
    sqlite_path: Path
    archive_path: Path


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required. Copy .env.example to .env and set it.")

    allowed_user_ids = _parse_allowed_user_ids(os.getenv("TELEGRAM_ALLOWED_USER_IDS", ""))
    if not allowed_user_ids:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS is required. Use comma-separated numeric Telegram user IDs.")

    return Settings(
        telegram_bot_token=token,
        telegram_allowed_user_ids=frozenset(allowed_user_ids),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").strip(),
        llm_api_key=_optional_env("LLM_API_KEY"),
        llm_model=_optional_env("LLM_MODEL"),
        vault_path=Path(os.getenv("VAULT_PATH", "/data/research-vault")),
        sqlite_path=Path(os.getenv("SQLITE_PATH", "/data/prism.sqlite3")),
        archive_path=Path(os.getenv("ARCHIVE_PATH", "/data/archives")),
    )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


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

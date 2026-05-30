"""Service singletons and FastAPI dependency providers.

Mirrors the wiring in `prism.bot.PrismBot.__init__` so the web app shares the
exact same SQLite / LanceDB / vault as the Telegram bot. Services are built
lazily on first request, so importing this module never requires env vars
(tests override the providers via `app.dependency_overrides`).

`PrismDatabase.connect()` opens a fresh connection per call, so a single
process-wide instance is safe to use from FastAPI's threadpool.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from prism.config import Settings, load_settings
from prism.db import PrismDatabase
from prism.embedding import EmbeddingConfig
from prism.ideas import IdeaService
from prism.index import NoteIndexer
from prism.llm import LLMConfig
from prism.notes import NoteService


@dataclass(frozen=True)
class Services:
    settings: Settings
    database: PrismDatabase
    indexer: NoteIndexer
    notes: NoteService
    ideas: IdeaService


def build_services(settings: Settings) -> Services:
    database = PrismDatabase(settings.sqlite_path)
    llm_config = LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    indexer = NoteIndexer(
        settings.lancedb_path,
        EmbeddingConfig(settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model),
    )
    notes = NoteService(settings.vault_path, database, settings.archive_path, llm_config, indexer)
    ideas = IdeaService(settings.vault_path, database, llm_config, indexer)
    return Services(settings=settings, database=database, indexer=indexer, notes=notes, ideas=ideas)


@lru_cache(maxsize=1)
def get_services() -> Services:
    return build_services(load_settings(require_telegram=False))


def get_db() -> PrismDatabase:
    return get_services().database


def get_notes() -> NoteService:
    return get_services().notes


def get_ideas() -> IdeaService:
    return get_services().ideas


def get_indexer() -> NoteIndexer:
    return get_services().indexer

"""Shared service wiring used by every entry point (bot, web, worker).

Mirrors the wiring in `prism.bot.PrismBot.__init__` so all processes share the
exact same SQLite / LanceDB / vault. Importing this module never requires env
vars; callers pass an already-loaded `Settings`.
"""
from __future__ import annotations

from dataclasses import dataclass

from prism.config import Settings
from prism.db import PrismDatabase
from prism.embedding import EmbeddingConfig
from prism.ideas import IdeaService
from prism.index import NoteIndexer
from prism.llm import LLMConfig
from prism.notes import NoteService
from prism.usage import set_usage_sink


@dataclass(frozen=True)
class Services:
    settings: Settings
    database: PrismDatabase
    indexer: NoteIndexer
    notes: NoteService
    ideas: IdeaService


def build_services(settings: Settings) -> Services:
    database = PrismDatabase(settings.sqlite_path)
    # Persist token usage from every LLM/embedding call into the shared DB so all
    # processes (bot/web/worker) contribute to one running total.
    set_usage_sink(lambda _kind, prompt, completion, total: database.add_token_usage(prompt, completion, total))
    llm_config = LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    indexer = NoteIndexer(
        settings.lancedb_path,
        EmbeddingConfig(settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model),
    )
    notes = NoteService(settings.vault_path, database, settings.archive_path, llm_config, indexer)
    ideas = IdeaService(settings.vault_path, database, llm_config, indexer)
    return Services(settings=settings, database=database, indexer=indexer, notes=notes, ideas=ideas)

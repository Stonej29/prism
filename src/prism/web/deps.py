"""FastAPI dependency providers over the shared service layer.

Services are built lazily on first request, so importing this module never
requires env vars (tests override the providers via `app.dependency_overrides`).

`PrismDatabase.connect()` opens a fresh connection per call, so a single
process-wide instance is safe to use from FastAPI's threadpool.
"""
from __future__ import annotations

from functools import lru_cache

from prism.config import Settings, load_settings
from prism.db import PrismDatabase
from prism.ideas import IdeaService
from prism.index import NoteIndexer
from prism.notes import NoteService
from prism.proposals import ProposalService
from prism.services import Services, build_services

__all__ = [
    "Services",
    "build_services",
    "get_services",
    "get_settings",
    "get_db",
    "get_notes",
    "get_ideas",
    "get_indexer",
    "get_proposals",
]


@lru_cache(maxsize=1)
def get_services() -> Services:
    return build_services(load_settings(require_telegram=False))


def get_settings() -> Settings:
    return get_services().settings


def get_db() -> PrismDatabase:
    return get_services().database


def get_notes() -> NoteService:
    return get_services().notes


def get_ideas() -> IdeaService:
    return get_services().ideas


def get_indexer() -> NoteIndexer:
    return get_services().indexer


def get_proposals() -> ProposalService:
    services = get_services()
    return ProposalService(services.database, services.notes)

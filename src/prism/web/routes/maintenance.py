from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends

from prism.config import Settings
from prism.db import PrismDatabase
from prism.ideas import IdeaService
from prism.index import NoteIndexer
from prism.notes import NoteService
from prism.services import Services
from prism.web.deps import get_db, get_ideas, get_indexer, get_notes, get_settings
from prism.web.schemas import TraversalSettingsBody
from prism.worker.config import TraversalSettings, load_worker_config, save_traversal_settings
from prism.worker.ingest import run_feed_ingestion
from prism.worker.traversal import run_graph_traversal

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


def _settings_dto(s: TraversalSettings) -> dict:
    return {
        "link_threshold": s.link_threshold,
        "max_links_per_note": s.max_links_per_note,
        "max_auto_links": s.max_auto_links,
        "dup_threshold": s.dup_threshold,
    }


@router.post("/ingest")
def trigger_ingest(notes: NoteService = Depends(get_notes)) -> dict:
    config = load_worker_config()
    summary = run_feed_ingestion(notes, config.feeds)
    return {"ok": True, "feeds_configured": len(config.feeds), **dataclasses.asdict(summary)}


@router.post("/traverse")
def trigger_traverse(
    settings: Settings = Depends(get_settings),
    db: PrismDatabase = Depends(get_db),
    notes: NoteService = Depends(get_notes),
    indexer: NoteIndexer = Depends(get_indexer),
    ideas: IdeaService = Depends(get_ideas),
) -> dict:
    services = Services(settings=settings, database=db, indexer=indexer, notes=notes, ideas=ideas)
    summary = run_graph_traversal(services, load_worker_config().traversal)
    return {"ok": True, "pending_proposals": db.count_proposals("pending"), **dataclasses.asdict(summary)}


@router.get("/settings")
def get_maintenance_settings() -> dict:
    return _settings_dto(load_worker_config().traversal)


@router.put("/settings")
def put_maintenance_settings(body: TraversalSettingsBody) -> dict:
    current = load_worker_config().traversal
    updated = TraversalSettings(
        link_threshold=body.link_threshold if body.link_threshold is not None else current.link_threshold,
        max_links_per_note=body.max_links_per_note if body.max_links_per_note is not None else current.max_links_per_note,
        max_auto_links=body.max_auto_links if body.max_auto_links is not None else current.max_auto_links,
        dup_threshold=body.dup_threshold if body.dup_threshold is not None else current.dup_threshold,
    )
    save_traversal_settings(updated)
    # Round-trip through the loader so clamping/validation is reflected back.
    return _settings_dto(load_worker_config().traversal)

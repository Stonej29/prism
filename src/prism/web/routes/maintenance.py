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
from prism.worker.config import load_worker_config
from prism.worker.ingest import run_feed_ingestion
from prism.worker.traversal import run_graph_traversal

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


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
    summary = run_graph_traversal(services)
    return {"ok": True, "pending_proposals": db.count_proposals("pending"), **dataclasses.asdict(summary)}

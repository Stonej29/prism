from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.index import NoteIndexer
from prism.notes import NoteService
from prism.web.deps import get_db, get_indexer, get_notes
from prism.web.serializers import stats_dto

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats(
    db: PrismDatabase = Depends(get_db),
    indexer: NoteIndexer = Depends(get_indexer),
    notes: NoteService = Depends(get_notes),
) -> dict:
    stats = db.get_note_stats()
    tags = db.list_tags_with_counts()
    return {
        "notes": stats_dto(stats),
        "tags": len(tags),
        "index_configured": indexer.is_configured,
        "embedding_model": indexer.embedding_config.model,
        "llm_configured": notes.llm_config.is_configured,
        "llm_model": notes.llm_config.model,
    }


@router.get("/usage")
def get_usage(db: PrismDatabase = Depends(get_db)) -> dict:
    u = db.get_token_usage()
    return {
        "total_tokens": u.total_tokens,
        "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens,
        "calls": u.calls,
        "today_total_tokens": u.today_total_tokens,
        "today_calls": u.today_calls,
    }

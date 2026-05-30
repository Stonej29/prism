from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.index import NoteIndexer
from prism.web.deps import get_db, get_indexer
from prism.web.serializers import stats_dto

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats(
    db: PrismDatabase = Depends(get_db),
    indexer: NoteIndexer = Depends(get_indexer),
) -> dict:
    stats = db.get_note_stats()
    tags = db.list_tags_with_counts()
    return {
        "notes": stats_dto(stats),
        "tags": len(tags),
        "index_configured": indexer.is_configured,
        "embedding_model": indexer.embedding_config.model,
    }

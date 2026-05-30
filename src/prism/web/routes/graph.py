from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.index import NoteIndexer
from prism.web.deps import get_db, get_indexer
from prism.web.graph import build_graph
from prism.web.routes import gather_all_notes

router = APIRouter(tags=["graph"])


@router.get("/graph")
def get_graph(
    source: str | None = None,
    db: PrismDatabase = Depends(get_db),
    indexer: NoteIndexer = Depends(get_indexer),
) -> dict:
    records = gather_all_notes(db)
    try:
        vectors = indexer.all_vectors()
    except Exception:
        vectors = {}
    return build_graph(records, vectors, source_filter=source)

from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.index import NoteIndexer
from prism.web.deps import get_db, get_indexer
from prism.web.graph import build_graph
from prism.web.routes import filter_notes, gather_all_notes

router = APIRouter(tags=["graph"])


@router.get("/graph")
def get_graph(
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_score: float | None = None,
    db: PrismDatabase = Depends(get_db),
    indexer: NoteIndexer = Depends(get_indexer),
) -> dict:
    records = filter_notes(
        gather_all_notes(db), date_from=date_from, date_to=date_to, min_score=min_score
    )
    try:
        vectors = indexer.all_vectors()
    except Exception:
        vectors = {}
    return build_graph(records, vectors, source_filter=source)

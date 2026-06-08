from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.index import NoteIndexer
from prism.notes import NoteService
from prism.web.deps import get_indexer, get_notes
from prism.web.schemas import AskBody
from prism.web.serializers import candidate_dto

router = APIRouter(tags=["search"])


@router.get("/find")
def find(q: str, limit: int | None = None, indexer: NoteIndexer = Depends(get_indexer)) -> dict:
    query, result_limit = parse_find_query(q, limit)
    if not query:
        return {"results": [], "configured": indexer.is_configured, "query": query, "limit": result_limit}
    if not indexer.is_configured:
        return {"results": [], "configured": False, "query": query, "limit": result_limit}
    try:
        results = indexer.search_text(query, limit=result_limit)
    except Exception as exc:  # noqa: BLE001 - surface as empty + message
        return {"results": [], "configured": True, "query": query, "limit": result_limit, "error": f"{type(exc).__name__}: {exc}"}
    return {"results": [candidate_dto(c) for c in results], "configured": True, "query": query, "limit": result_limit}


def parse_find_query(q: str, limit: int | None = None) -> tuple[str, int]:
    parts = q.strip().split()
    requested = limit
    if len(parts) > 1 and parts[-1].isdigit():
        requested = int(parts[-1])
        parts = parts[:-1]
    result_limit = max(1, min(20, int(requested or 1)))
    return " ".join(parts), result_limit


@router.post("/ask")
def ask(body: AskBody, notes: NoteService = Depends(get_notes)) -> dict:
    result = notes.ask(body.question, body.limit)
    return {
        "ok": result.ok,
        "answer": result.answer,
        "message": result.message,
        "sources": [candidate_dto(c) for c in result.sources],
    }

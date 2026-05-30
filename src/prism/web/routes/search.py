from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.index import NoteIndexer
from prism.notes import NoteService
from prism.web.deps import get_indexer, get_notes
from prism.web.schemas import AskBody
from prism.web.serializers import candidate_dto

router = APIRouter(tags=["search"])


@router.get("/find")
def find(q: str, limit: int = 20, indexer: NoteIndexer = Depends(get_indexer)) -> dict:
    if not q.strip():
        return {"results": [], "configured": indexer.is_configured}
    if not indexer.is_configured:
        return {"results": [], "configured": False}
    try:
        results = indexer.search_text(q, limit=limit)
    except Exception as exc:  # noqa: BLE001 - surface as empty + message
        return {"results": [], "configured": True, "error": f"{type(exc).__name__}: {exc}"}
    return {"results": [candidate_dto(c) for c in results], "configured": True}


@router.post("/ask")
def ask(body: AskBody, notes: NoteService = Depends(get_notes)) -> dict:
    result = notes.ask(body.question, body.limit)
    return {
        "ok": result.ok,
        "answer": result.answer,
        "message": result.message,
        "sources": [candidate_dto(c) for c in result.sources],
    }

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from prism.notes import NoteService
from prism.web.deps import get_notes
from prism.web.serializers import candidate_dto, note_summary_dto

router = APIRouter(tags=["rediscovery"])

_STRATEGIES = ("on_this_day", "forgotten_gems", "related")


@router.get("/rediscovery")
def rediscover(
    strategy: str = "on_this_day",
    note_id: str | None = None,
    limit: int = 12,
    notes: NoteService = Depends(get_notes),
) -> dict:
    """Surface forgotten/contextual knowledge.

    - on_this_day: notes saved on today's date previously
    - forgotten_gems: high-scoring, unreviewed, >30d old (Keep excluded)
    - related: live semantic neighbours of ``note_id``
    """
    if strategy not in _STRATEGIES:
        raise HTTPException(status_code=400, detail=f"strategy must be one of {', '.join(_STRATEGIES)}")
    if strategy == "related":
        if not note_id:
            raise HTTPException(status_code=400, detail="note_id is required for strategy=related")
        items = [candidate_dto(c) for c in notes.rediscover_related(note_id, limit)]
    elif strategy == "forgotten_gems":
        items = [note_summary_dto(r) for r in notes.rediscover_forgotten_gems(limit)]
    else:
        items = [note_summary_dto(r) for r in notes.rediscover_on_this_day(limit)]
    return {"strategy": strategy, "items": items}

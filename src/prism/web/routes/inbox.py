from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.web.deps import get_db
from prism.web.serializers import note_summary_dto

router = APIRouter(tags=["inbox"])

_SORTS = ("newest", "oldest", "relevance", "by_purpose")


@router.get("/inbox")
def get_inbox(
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
    db: PrismDatabase = Depends(get_db),
) -> dict:
    """The review queue: unreviewed notes worth reading (Keep + archived excluded)."""
    if sort not in _SORTS:
        sort = "newest"
    records = db.list_inbox_notes(limit, offset, sort)
    stats = db.get_note_stats()
    return {
        "items": [note_summary_dto(r) for r in records],
        "sort": sort,
        "count": stats.inbox,
    }

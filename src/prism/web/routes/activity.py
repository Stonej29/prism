from __future__ import annotations

from fastapi import APIRouter

from prism.web.activity import activity_entries

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("")
def get_activity(limit: int = 100) -> dict:
    clamped = max(1, min(200, int(limit)))
    return {"items": activity_entries(clamped), "limit": clamped}

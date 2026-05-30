from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.web.deps import get_db

router = APIRouter(tags=["tags"])


@router.get("/tags")
def list_tags(db: PrismDatabase = Depends(get_db)) -> dict:
    items = [{"tag": tag, "count": count} for tag, count in db.list_tags_with_counts()]
    return {"items": items}

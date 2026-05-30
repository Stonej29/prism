from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.web.deps import get_db
from prism.web.graph import build_graph
from prism.web.routes import gather_all_notes

router = APIRouter(tags=["graph"])


@router.get("/graph")
def get_graph(source: str | None = None, db: PrismDatabase = Depends(get_db)) -> dict:
    return build_graph(gather_all_notes(db), source_filter=source)

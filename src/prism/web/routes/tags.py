from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.db import PrismDatabase
from prism.notes import NoteService
from prism.web.deps import get_db, get_notes
from prism.web.schemas import MergeTagBody

router = APIRouter(tags=["tags"])


@router.get("/tags")
def list_tags(db: PrismDatabase = Depends(get_db)) -> dict:
    items = [{"tag": tag, "count": count} for tag, count in db.list_tags_with_counts()]
    return {"items": items}


@router.delete("/tags/{tag}")
def delete_tag(tag: str, notes: NoteService = Depends(get_notes)) -> dict:
    """Remove a tag from every note that has it (global cleanup of broad tags)."""
    updated = notes.remove_tag_everywhere(tag)
    return {"ok": True, "tag": tag, "notes_updated": updated}


@router.post("/tags/merge")
def merge_tags(body: MergeTagBody, notes: NoteService = Depends(get_notes)) -> dict:
    """Fold one tag into another across all notes."""
    updated = notes.merge_tag(body.source, body.target)
    return {"ok": True, "source": body.source, "target": body.target, "notes_updated": updated}

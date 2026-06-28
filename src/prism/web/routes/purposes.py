from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from prism.db import PrismDatabase, PurposeRecord
from prism.notes import NoteService, normalize_purpose
from prism.web.activity import log_activity
from prism.web.deps import get_db, get_notes
from prism.web.schemas import PurposeBody, PurposeUpdateBody

router = APIRouter(prefix="/purposes", tags=["purposes"])


def _dto(record: PurposeRecord) -> dict:
    return {"name": record.name, "description": record.description, "sort_order": record.sort_order}


@router.get("")
def list_purposes(db: PrismDatabase = Depends(get_db)) -> dict:
    return {"items": [_dto(p) for p in db.list_purposes()]}


@router.post("")
def create_purpose(body: PurposeBody, db: PrismDatabase = Depends(get_db)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if name.lower() in ("none", "unsorted"):
        raise HTTPException(status_code=400, detail="'Unsorted' is reserved.")
    # Reject a name that collides (case/separator-insensitive) with an existing purpose.
    if normalize_purpose(name, [p.name for p in db.list_purposes()]):
        raise HTTPException(status_code=409, detail=f"A purpose like '{name}' already exists.")
    record = db.add_purpose(name, body.description.strip())
    log_activity("purpose", "ok", f"Added purpose “{name}”")
    return _dto(record)


@router.put("/{name}")
def update_purpose(name: str, body: PurposeUpdateBody, db: PrismDatabase = Depends(get_db)) -> dict:
    if not db.update_purpose(name, body.description.strip()):
        raise HTTPException(status_code=404, detail=f"No purpose named '{name}'.")
    log_activity("purpose", "ok", f"Updated purpose “{name}”")
    return {"name": name, "description": body.description.strip()}


@router.delete("/{name}")
def delete_purpose(name: str, db: PrismDatabase = Depends(get_db)) -> dict:
    if not db.delete_purpose(name):
        raise HTTPException(status_code=404, detail=f"No purpose named '{name}'.")
    log_activity("purpose", "ok", f"Deleted purpose “{name}”")
    return {"ok": True}


@router.post("/scan")
def scan_purposes(notes: NoteService = Depends(get_notes)) -> dict:
    """Re-classify non-user notes against the current purpose set, writing review proposals."""
    summary = notes.propose_reclassification()
    log_activity("purpose scan", "ok" if summary.ok else "failed", summary.message, created=summary.created, scanned=summary.scanned)
    return {"ok": summary.ok, "created": summary.created, "scanned": summary.scanned, "message": summary.message}

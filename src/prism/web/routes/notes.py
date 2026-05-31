from __future__ import annotations

import json
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException

from prism.db import PrismDatabase
from prism.notes import NOTE_STATUSES, NoteService, _tags
from prism.web.deps import get_db, get_notes
from prism.web.routes import gather_all_notes
from prism.web.schemas import BulkStatusBody, EditTagsBody, JobFlagBody, RenameBody, SaveUrlBody, SetStatusBody
from prism.web.serializers import note_summary_dto, note_to_dto

router = APIRouter(prefix="/notes", tags=["notes"])


def _status_match(record, status: str | None) -> bool:
    if status is None:
        return record.status != "archived"
    if status == "all":
        return True
    return record.status == status


@router.get("")
def list_notes(
    source: str | None = None,
    input_source: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: PrismDatabase = Depends(get_db),
) -> dict:
    if tag:
        records = db.list_notes_by_tag(tag, limit, offset, status)
    elif input_source:
        records = db.list_notes_by_input_source(input_source, limit, offset, status)
    elif source:
        filtered = [r for r in gather_all_notes(db) if r.source_kind == source and _status_match(r, status)]
        records = filtered[offset : offset + limit]
    else:
        records = db.list_recent_notes(limit, offset, status)
    return {"items": [note_summary_dto(r) for r in records], "limit": limit, "offset": offset}


@router.get("/{note_id}")
def get_note(note_id: str, db: PrismDatabase = Depends(get_db)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    return note_to_dto(record)


@router.post("")
def save_url(body: SaveUrlBody, notes: NoteService = Depends(get_notes)) -> dict:
    result = notes.save_url(body.url.strip(), body.input_source.strip() or "web_ui")
    return {
        "created": result.created,
        "duplicate_reason": result.duplicate_reason,
        "note": note_to_dto(result.record),
    }


@router.post("/retry-failed")
def retry_failed(limit: int = 25, notes: NoteService = Depends(get_notes)) -> dict:
    result = notes.retry_failed(limit)
    return {
        "total": result.total,
        "retried": result.retried,
        "repaired": result.repaired,
        "failed": result.failed,
        "skipped": result.skipped,
        "messages": result.messages,
    }


@router.post("/{note_id}/reprocess")
def reprocess(note_id: str, notes: NoteService = Depends(get_notes)) -> dict:
    result = notes.reprocess(note_id)
    if not result.record:
        raise HTTPException(status_code=404, detail=result.message)
    return {"ok": result.ok, "message": result.message, "note": note_to_dto(result.record)}


@router.delete("/{note_id}")
def delete_note(note_id: str, notes: NoteService = Depends(get_notes)) -> dict:
    result = notes.delete_note(note_id)
    if not result.ok:
        raise HTTPException(status_code=404, detail=result.message)
    return {"ok": result.ok, "message": result.message, "title": result.title}


@router.put("/{note_id}/tags")
def edit_tags(note_id: str, body: EditTagsBody, db: PrismDatabase = Depends(get_db)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    cleaned = _tags(body.tags)
    updated = replace(record, tags_json=json.dumps(cleaned, ensure_ascii=True))
    db.update_note(updated)
    return note_to_dto(updated)


@router.put("/{note_id}/title")
def rename_note(note_id: str, body: RenameBody, db: PrismDatabase = Depends(get_db), notes: NoteService = Depends(get_notes)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    try:
        updated = notes.rename_note(record, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return note_to_dto(updated)


@router.put("/{note_id}/job_flag")
def set_job_flag(note_id: str, body: JobFlagBody, db: PrismDatabase = Depends(get_db)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    db.set_job_flag(record.note_id, body.value)
    return note_to_dto(db.find_by_note_id(record.note_id))


@router.put("/{note_id}/status")
def set_status(note_id: str, body: SetStatusBody, db: PrismDatabase = Depends(get_db), notes: NoteService = Depends(get_notes)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    try:
        updated = notes.set_status(record, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return note_to_dto(updated)


@router.put("/status")
def set_status_bulk(body: BulkStatusBody, db: PrismDatabase = Depends(get_db), notes: NoteService = Depends(get_notes)) -> dict:
    if body.status not in NOTE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {', '.join(NOTE_STATUSES)}")
    results = []
    for note_id in body.ids:
        record = db.find_by_note_id(note_id.strip().lower())
        if not record:
            results.append({"id": note_id, "ok": False})
            continue
        updated = notes.set_status(record, body.status)
        results.append({"id": updated.note_id, "ok": True, "status": updated.status})
    return {"status": body.status, "results": results}

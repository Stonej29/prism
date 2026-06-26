from __future__ import annotations

import json
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException

from prism.db import PrismDatabase
from prism.notes import NOTE_STATUSES, NoteService, _tags
from prism.web.activity import log_activity
from prism.web.deps import get_db, get_notes
from prism.web.routes import filter_notes, gather_all_notes
from prism.web.schemas import BulkStatusBody, EditTagsBody, FavoriteBody, RenameBody, SaveUrlBody, SetPurposeBody, SetStatusBody
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
    date_from: str | None = None,
    date_to: str | None = None,
    min_score: float | None = None,
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
    records = filter_notes(records, date_from=date_from, date_to=date_to, min_score=min_score)
    return {"items": [note_summary_dto(r) for r in records], "limit": limit, "offset": offset}


@router.get("/{note_id}")
def get_note(note_id: str, db: PrismDatabase = Depends(get_db)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    return note_to_dto(record)


@router.post("")
def save_url(body: SaveUrlBody, notes: NoteService = Depends(get_notes)) -> dict:
    url = body.url.strip()
    try:
        result = notes.save_url(url, body.input_source.strip() or "web_ui", force=body.force)
    except Exception as exc:
        log_activity("save url", "failed", f"{type(exc).__name__}: {exc}", url=url)
        raise
    status = "ok" if result.created else "duplicate"
    message = f"Saved {result.record.title}" if result.created else f"Already saved {result.record.title}"
    log_activity("save url", status, message, note_id=result.record.note_id, url=url, duplicate_reason=result.duplicate_reason)
    return {
        "created": result.created,
        "duplicate_reason": result.duplicate_reason,
        "similar_note_id": result.similar_note_id,
        "similarity": result.similarity,
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


@router.post("/reprocess-all")
def reprocess_all(notes: NoteService = Depends(get_notes)) -> dict:
    summary = notes.reprocess_all()
    log_activity("reprocess_all", "ok" if not summary.failed else "failed",
                 f"reprocessed {summary.reprocessed}/{summary.total}, {summary.failed} failed")
    return {
        "total": summary.total,
        "reprocessed": summary.reprocessed,
        "failed": summary.failed,
        "errors": summary.errors,
    }


@router.post("/{note_id}/reprocess")
def reprocess(note_id: str, notes: NoteService = Depends(get_notes)) -> dict:
    try:
        result = notes.reprocess(note_id)
    except Exception as exc:
        log_activity("reprocess", "failed", f"{type(exc).__name__}: {exc}", note_id=note_id)
        raise
    if not result.record:
        log_activity("reprocess", "failed", result.message, note_id=note_id)
        raise HTTPException(status_code=404, detail=result.message)
    log_activity("reprocess", "ok" if result.ok else "failed", result.message, note_id=result.record.note_id)
    return {"ok": result.ok, "message": result.message, "note": note_to_dto(result.record)}


@router.post("/{note_id}/repersonalize")
def repersonalize(note_id: str, notes: NoteService = Depends(get_notes)) -> dict:
    try:
        result = notes.repersonalize(note_id)
    except Exception as exc:
        log_activity("repersonalize", "failed", f"{type(exc).__name__}: {exc}", note_id=note_id)
        raise
    if not result.record:
        log_activity("repersonalize", "failed", result.message, note_id=note_id)
        raise HTTPException(status_code=404, detail=result.message)
    log_activity("repersonalize", "ok" if result.ok else "failed", result.message, note_id=result.record.note_id)
    return {"ok": result.ok, "message": result.message, "note": note_to_dto(result.record)}


@router.post("/{note_id}/research")
def research_note(note_id: str, notes: NoteService = Depends(get_notes)) -> dict:
    try:
        result = notes.research_note(note_id)
    except Exception as exc:
        log_activity("research", "failed", f"{type(exc).__name__}: {exc}", note_id=note_id)
        raise
    if not result.record:
        log_activity("research", "failed", result.message, note_id=note_id)
        raise HTTPException(status_code=404, detail=result.message)
    log_activity("research", "ok" if result.ok else "failed", result.message, note_id=result.record.note_id)
    return {"ok": result.ok, "message": result.message, "note": note_to_dto(result.record)}


@router.post("/{note_id}/extract-images")
def extract_images(note_id: str, notes: NoteService = Depends(get_notes)) -> dict:
    try:
        result = notes.extract_images(note_id)
    except Exception as exc:
        log_activity("extract_images", "failed", f"{type(exc).__name__}: {exc}", note_id=note_id)
        raise
    if not result.record:
        log_activity("extract_images", "failed", result.message, note_id=note_id)
        raise HTTPException(status_code=404, detail=result.message)
    log_activity("extract_images", "ok" if result.ok else "failed", result.message, note_id=result.record.note_id)
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


@router.put("/{note_id}/favorite")
def set_favorite(note_id: str, body: FavoriteBody, db: PrismDatabase = Depends(get_db)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    db.set_favorite(record.note_id, body.value)
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


@router.put("/{note_id}/purpose")
def set_purpose(note_id: str, body: SetPurposeBody, db: PrismDatabase = Depends(get_db), notes: NoteService = Depends(get_notes)) -> dict:
    record = db.find_by_note_id(note_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No note found for {note_id}")
    try:
        updated = notes.set_purpose(record, body.purpose)
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

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from prism.config import Settings
from prism.db import PrismDatabase
from prism.ideas import IdeaService
from prism.index import NoteIndexer
from prism.notes import NoteService
from prism.services import Services
from prism.web.activity import log_activity
from prism.web.deps import get_db, get_ideas, get_indexer, get_notes, get_settings
from prism.web.graph import link_origin_counts
from prism.web.routes import gather_all_notes
from prism.web.schemas import TraversalSettingsBody
from prism.worker.config import TraversalSettings, load_worker_config, save_traversal_settings
from prism.worker.ingest import run_feed_ingestion
from prism.worker.traversal import run_graph_traversal

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
_EVENT_LIMIT = 500
_STATUS_LOCK = Lock()
_STATUS: dict[str, Any] = {
    "status": "idle",
    "run_id": None,
    "started_at": None,
    "finished_at": None,
    "last_seq": 0,
    "events": [],
    "summary": None,
    "error": None,
}


@router.get("/status")
def maintenance_status() -> dict:
    return _status_snapshot()


def _settings_dto(s: TraversalSettings) -> dict:
    return {
        "link_threshold": s.link_threshold,
        "max_links_per_note": s.max_links_per_note,
        "max_auto_links": s.max_auto_links,
        "dup_threshold": s.dup_threshold,
    }


@router.post("/ingest")
def trigger_ingest(notes: NoteService = Depends(get_notes)) -> dict:
    config = load_worker_config()
    try:
        summary = run_feed_ingestion(notes, config.feeds)
    except Exception as exc:
        log_activity("feed ingest", "failed", f"{type(exc).__name__}: {exc}", feeds_configured=len(config.feeds))
        raise
    payload = {"ok": True, "feeds_configured": len(config.feeds), **dataclasses.asdict(summary)}
    log_activity(
        "feed ingest",
        "ok" if summary.failed == 0 else "failed",
        f"{summary.created} created, {summary.duplicates} duplicates, {summary.failed} failed",
        feeds_configured=len(config.feeds),
        created=summary.created,
        duplicates=summary.duplicates,
        failed=summary.failed,
    )
    return payload


@router.post("/traverse")
def trigger_traverse(
    settings: Settings = Depends(get_settings),
    db: PrismDatabase = Depends(get_db),
    notes: NoteService = Depends(get_notes),
    indexer: NoteIndexer = Depends(get_indexer),
    ideas: IdeaService = Depends(get_ideas),
) -> dict:
    traversal_settings = load_worker_config().traversal
    settings_payload = _settings_dto(traversal_settings)
    run_id = _start_run()
    services = Services(settings=settings, database=db, indexer=indexer, notes=notes, ideas=ideas)
    links_before = link_origin_counts(gather_all_notes(db))
    _append_event(run_id, {"kind": "settings", "message": "Using graph maintenance settings", "settings": settings_payload})
    _append_event(run_id, {"kind": "link_origins", "phase": "before", "message": "Link origins before maintenance", "counts": links_before})
    try:
        summary = run_graph_traversal(
            services,
            traversal_settings,
            emit_event=lambda event: _append_event(run_id, event),
        )
        links_after = link_origin_counts(gather_all_notes(db))
        _append_event(run_id, {"kind": "link_origins", "phase": "after", "message": "Link origins after maintenance", "counts": links_after})
        payload = {
            "ok": True,
            "pending_proposals": db.count_proposals("pending"),
            "settings": settings_payload,
            "links_by_origin_before": links_before,
            "links_by_origin_after": links_after,
            **dataclasses.asdict(summary),
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _finish_run(run_id, status="failed", error=error)
        log_activity("maintenance run", "failed", error, settings=settings_payload, links_by_origin_before=links_before)
        raise
    _finish_run(run_id, status="complete", summary=payload)
    log_activity(
        "maintenance run",
        "ok",
        f"links +{summary.links_added}/-{summary.links_removed}, {summary.tags_merged} tags merged, {summary.duplicates_proposed} proposals",
        settings=settings_payload,
        links_by_origin_before=links_before,
        links_by_origin_after=payload["links_by_origin_after"],
    )
    return payload


@router.get("/settings")
def get_maintenance_settings() -> dict:
    return _settings_dto(load_worker_config().traversal)


@router.put("/settings")
def put_maintenance_settings(body: TraversalSettingsBody) -> dict:
    current = load_worker_config().traversal
    updated = TraversalSettings(
        link_threshold=body.link_threshold if body.link_threshold is not None else current.link_threshold,
        max_links_per_note=body.max_links_per_note if body.max_links_per_note is not None else current.max_links_per_note,
        max_auto_links=body.max_auto_links if body.max_auto_links is not None else current.max_auto_links,
        dup_threshold=body.dup_threshold if body.dup_threshold is not None else current.dup_threshold,
    )
    save_traversal_settings(updated)
    # Round-trip through the loader so clamping/validation is reflected back.
    saved = _settings_dto(load_worker_config().traversal)
    log_activity("maintenance settings", "ok", "Saved graph maintenance settings", settings=saved)
    return saved


def _start_run() -> str:
    now = _now()
    with _STATUS_LOCK:
        if _STATUS["status"] == "running":
            raise HTTPException(status_code=409, detail="Graph maintenance is already running")
        run_id = now
        _STATUS.update({
            "status": "running",
            "run_id": run_id,
            "started_at": now,
            "finished_at": None,
            "last_seq": 0,
            "events": [],
            "summary": None,
            "error": None,
        })
    return run_id


def _append_event(run_id: str, event: dict[str, Any]) -> None:
    with _STATUS_LOCK:
        if _STATUS.get("run_id") != run_id:
            return
        seq = int(_STATUS.get("last_seq") or 0) + 1
        entry = {"seq": seq, "at": _now(), **event}
        events = [*_STATUS.get("events", []), entry][-_EVENT_LIMIT:]
        _STATUS["last_seq"] = seq
        _STATUS["events"] = events


def _finish_run(run_id: str, *, status: str, summary: dict[str, Any] | None = None, error: str | None = None) -> None:
    with _STATUS_LOCK:
        if _STATUS.get("run_id") != run_id:
            return
        _STATUS.update({
            "status": status,
            "finished_at": _now(),
            "summary": summary,
            "error": error,
        })


def _status_snapshot() -> dict[str, Any]:
    with _STATUS_LOCK:
        events = [dict(event) for event in _STATUS.get("events", [])]
        return {
            "status": _STATUS["status"],
            "run_id": _STATUS["run_id"],
            "started_at": _STATUS["started_at"],
            "finished_at": _STATUS["finished_at"],
            "last_seq": _STATUS["last_seq"],
            "events": events,
            "event_count": len(events),
            "summary": _STATUS["summary"],
            "error": _STATUS["error"],
        }


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

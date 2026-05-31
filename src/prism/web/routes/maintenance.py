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
from prism.web.deps import get_db, get_ideas, get_indexer, get_notes, get_settings
from prism.worker.config import load_worker_config
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


@router.post("/ingest")
def trigger_ingest(notes: NoteService = Depends(get_notes)) -> dict:
    config = load_worker_config()
    summary = run_feed_ingestion(notes, config.feeds)
    return {"ok": True, "feeds_configured": len(config.feeds), **dataclasses.asdict(summary)}


@router.post("/traverse")
def trigger_traverse(
    settings: Settings = Depends(get_settings),
    db: PrismDatabase = Depends(get_db),
    notes: NoteService = Depends(get_notes),
    indexer: NoteIndexer = Depends(get_indexer),
    ideas: IdeaService = Depends(get_ideas),
) -> dict:
    run_id = _start_run()
    services = Services(settings=settings, database=db, indexer=indexer, notes=notes, ideas=ideas)
    try:
        summary = run_graph_traversal(services, emit_event=lambda event: _append_event(run_id, event))
        payload = {"ok": True, "pending_proposals": db.count_proposals("pending"), **dataclasses.asdict(summary)}
    except Exception as exc:
        _finish_run(run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    _finish_run(run_id, status="complete", summary=payload)
    return payload


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

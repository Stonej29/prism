"""Turn frozen dataclasses with raw JSON columns into JSON-friendly dicts.

Reuses the pure helpers in `prism.notes` / `prism.index` rather than
re-parsing the `*_json` columns by hand.
"""
from __future__ import annotations

import dataclasses
from typing import Any
from urllib.parse import quote

from prism.db import ChatMessageRecord, IdeaRecord, NoteRecord, NoteStats, ProposalRecord
from prism.index import RelatedCandidate
from prism.notes import (
    _json_array,
    _json_object,
    related_notes_for_record,
    scores_for_record,
    structured_summary,
    tags_for_record,
)
from prism.proposals import describe_proposal, proposal_note_ids, proposal_payload


def images_for_record(record: NoteRecord) -> list[dict[str, Any]]:
    """Extracted-image entries as servable URLs (via the /api/file archive route)."""
    metadata = _json_object(record.metadata_json)
    out: list[dict[str, Any]] = []
    for entry in metadata.get("images") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("file")
        if not name:
            continue
        path = quote(f"{record.note_id}/images/{name}")
        out.append({"url": f"/api/file?root=archive&path={path}", "width": entry.get("w"), "height": entry.get("h")})
    return out


def note_summary_dto(record: NoteRecord) -> dict[str, Any]:
    """Compact shape for list views and graph nodes."""
    scores = scores_for_record(record)
    return {
        "id": record.note_id,
        "title": record.title,
        "summary": record.summary,
        "source_url": record.source_url,
        "source_kind": record.source_kind,
        "input_source": record.input_source,
        "date_saved": record.date_saved,
        "tags": tags_for_record(record),
        "overall": scores.get("overall"),
        "llm_status": record.llm_status,
        "favorite": bool(record.favorite),
        "purpose": record.purpose,
        "date_reviewed": record.date_reviewed,
        "thumbnail": (imgs[0]["url"] if (imgs := images_for_record(record)) else None),
        "image_count": len(imgs),
    }


def note_to_dto(record: NoteRecord) -> dict[str, Any]:
    """Full note detail for the right-hand pane."""
    metadata = _json_object(record.metadata_json)
    return {
        "id": record.note_id,
        "title": record.title,
        "summary": record.summary,
        "source_url": record.source_url,
        "resolved_url": record.resolved_url,
        "source_kind": record.source_kind,
        "input_source": record.input_source,
        "date_saved": record.date_saved,
        "fetched_at": record.fetched_at,
        "status": record.status,
        "fetch_status": record.fetch_status,
        "llm_status": record.llm_status,
        "llm_model": record.llm_model,
        "embedding_status": record.embedding_status,
        "embedding_dimensions": record.embedding_dimensions,
        "research_status": metadata.get("research_status"),
        "researched_at": metadata.get("researched_at"),
        "research_error": metadata.get("research_error"),
        "research_sources": metadata.get("research_sources") or [],
        "scores": scores_for_record(record),
        "tags": tags_for_record(record),
        "structured_summary": structured_summary(record),
        "related_notes": related_notes_for_record(record),
        "favorite": bool(record.favorite),
        "purpose": record.purpose,
        "date_reviewed": record.date_reviewed,
        "images": images_for_record(record),
        "reading_minutes": metadata.get("reading_minutes"),
        "title_source": metadata.get("title_source"),
        "details": _curated_metadata(metadata),
    }


# Source-specific metadata keys worth showing in the note "Details" block, in display order.
_DETAIL_KEYS = (
    ("authors", "Authors"),
    ("author_name", "Channel"),
    ("pdf_author", "Author"),
    ("published", "Published"),
    ("venue", "Venue"),
    ("stars", "Stars"),
    ("language", "Language"),
    ("license", "License"),
    ("content_type", "Type"),
)


def _curated_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """A small, display-ready subset of fetch metadata (label/value pairs)."""
    details: list[dict[str, Any]] = []
    for key, label in _DETAIL_KEYS:
        value = metadata.get(key)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value not in (None, "", []):
            details.append({"label": label, "value": value})
    return details


def idea_to_dto(record: IdeaRecord) -> dict[str, Any]:
    return {
        "id": record.idea_id,
        "title": record.title,
        "summary": record.summary,
        "topic": record.topic,
        "created_at": record.created_at,
        "rating": record.rating,
        "rated_at": record.rated_at,
        "llm_status": record.llm_status,
        "llm_model": record.llm_model,
        "tags": _json_array(record.tags_json),
        "source_note_ids": _json_array(record.source_note_ids_json),
        "structured": _json_object(record.structured_json),
    }


def candidate_dto(candidate: RelatedCandidate) -> dict[str, Any]:
    return {
        "id": candidate.note_id,
        "title": candidate.title,
        "summary": candidate.summary,
        "source_url": candidate.source_url,
        "path": candidate.note_path,
        "tags": candidate.tags,
        "score": round(candidate.score, 4),
    }


def chat_message_dto(record: ChatMessageRecord) -> dict[str, Any]:
    return {
        "role": record.role,
        "content": record.content,
        "created_at": record.created_at,
    }


def stats_dto(stats: NoteStats) -> dict[str, Any]:
    return dataclasses.asdict(stats)


def proposal_to_dto(record: ProposalRecord) -> dict[str, Any]:
    return {
        "id": record.proposal_id,
        "kind": record.kind,
        "status": record.status,
        "created_at": record.created_at,
        "resolved_at": record.resolved_at,
        "note_ids": proposal_note_ids(record),
        "payload": proposal_payload(record),
        "description": describe_proposal(record),
    }

"""Turn frozen dataclasses with raw JSON columns into JSON-friendly dicts.

Reuses the pure helpers in `prism.notes` / `prism.index` rather than
re-parsing the `*_json` columns by hand.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from prism.db import IdeaRecord, NoteRecord, NoteStats, ProposalRecord
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
        "job_relevant": bool(record.job_relevant),
    }


def note_to_dto(record: NoteRecord) -> dict[str, Any]:
    """Full note detail for the right-hand pane."""
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
        "scores": scores_for_record(record),
        "tags": tags_for_record(record),
        "structured_summary": structured_summary(record),
        "related_notes": related_notes_for_record(record),
        "job_relevant": bool(record.job_relevant),
    }


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

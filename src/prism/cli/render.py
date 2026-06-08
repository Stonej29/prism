"""Plain-text rendering of PRISM records for the CLI.

Reuses the serializer helpers in ``notes.py`` (``structured_summary``,
``scores_for_record`` …) rather than re-parsing the ``*_json`` columns.
"""
from __future__ import annotations

from prism.db import IdeaRecord, NoteRecord, ProposalRecord
from prism.index import RelatedCandidate
from prism.notes import (
    related_notes_for_record,
    scores_for_record,
    structured_summary,
    tags_for_record,
)
from prism.proposals import describe_proposal


def note_line(record: NoteRecord) -> str:
    return f"[{record.note_id}] {record.title} ({record.source_kind}, {record.date_saved[:10]})"


def candidate_line(c: RelatedCandidate) -> str:
    return f"[{c.note_id}] {c.title}  score={c.score:.2f}"


def idea_line(record: IdeaRecord) -> str:
    rating = record.rating if record.rating is not None else "-"
    return f"[{record.idea_id}] {record.title}  rating={rating}"


def proposal_line(record: ProposalRecord) -> str:
    return f"[{record.proposal_id}] {describe_proposal(record)}"


def note_detail(record: NoteRecord) -> str:
    s = structured_summary(record)
    generated = record.llm_status == "generated"
    lines: list[str] = [record.title, "=" * len(record.title)]

    quick = s.get("quick_summary") if generated else None
    lines.append(quick.strip() if isinstance(quick, str) and quick.strip() else record.summary)

    if generated:
        detailed = s.get("detailed_summary")
        if isinstance(detailed, str) and detailed.strip():
            lines += ["", "Detailed:", detailed.strip()]
        claims = s.get("key_claims")
        if isinstance(claims, list):
            picked = [f"- {str(c).strip()}" for c in claims[:5] if str(c).strip()]
            if picked:
                lines += ["", "Key claims:", *picked]
        limitations = s.get("limitations")
        if isinstance(limitations, list):
            picked = [f"- {str(x).strip()}" for x in limitations[:3] if str(x).strip()]
            if picked:
                lines += ["", "Limitations:", *picked]

    tags = tags_for_record(record)
    if tags:
        lines += ["", "Tags: " + ", ".join(tags)]

    scores = scores_for_record(record)
    if scores:
        parts = [f"{k} {int(scores[k])}" for k in ("relevance", "novelty", "overall") if k in scores]
        if parts:
            lines += ["Scores: " + " · ".join(parts)]

    related = related_notes_for_record(record)
    if related:
        lines += ["", "Related:"] + [f"- [{item['id']}] {item['title']}" for item in related[:5]]

    lines += ["", f"Source: {record.source_url}"]
    return "\n".join(lines)

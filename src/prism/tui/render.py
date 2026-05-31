"""Render PRISM records and results to Markdown for the detail pane.

Reuses the serializer helpers in ``notes.py`` (``structured_summary`` …) rather
than re-parsing the ``*_json`` columns.
"""
from __future__ import annotations

from prism.cli_core import StatusInfo
from prism.db import IdeaRecord, NoteRecord, ProposalRecord
from prism.ideas import _json_object
from prism.index import RelatedCandidate
from prism.notes import (
    related_notes_for_record,
    scores_for_record,
    structured_summary,
    tags_for_record,
)
from prism.proposals import describe_proposal


def note_markdown(record: NoteRecord) -> str:
    s = structured_summary(record)
    generated = record.llm_status == "generated"
    out: list[str] = [f"# {record.title}", ""]

    quick = s.get("quick_summary") if generated else None
    out.append(quick.strip() if isinstance(quick, str) and quick.strip() else record.summary)

    if generated:
        detailed = s.get("detailed_summary")
        if isinstance(detailed, str) and detailed.strip():
            out += ["", "## Detailed", detailed.strip()]
        claims = s.get("key_claims")
        if isinstance(claims, list):
            picked = [f"- {str(c).strip()}" for c in claims[:6] if str(c).strip()]
            if picked:
                out += ["", "## Key claims", *picked]
        limitations = s.get("limitations")
        if isinstance(limitations, list):
            picked = [f"- {str(x).strip()}" for x in limitations[:4] if str(x).strip()]
            if picked:
                out += ["", "## Limitations", *picked]

    tags = tags_for_record(record)
    if tags:
        out += ["", "**Tags:** " + ", ".join(f"`{t}`" for t in tags)]

    scores = scores_for_record(record)
    if scores:
        parts = [f"{k} {int(scores[k])}" for k in ("relevance", "novelty", "overall") if k in scores]
        if parts:
            out += ["", "**Scores:** " + " · ".join(parts)]

    related = related_notes_for_record(record)
    if related:
        out += ["", "## Related"] + [f"- `{item['id']}` {item['title']}" for item in related[:6]]

    out += ["", f"**Source:** {record.source_url}", "", f"`{record.note_id}` · {record.source_kind} · {record.date_saved[:10]}"]
    return "\n".join(out)


def idea_markdown(record: IdeaRecord) -> str:
    s = _json_object(record.structured_json)
    out: list[str] = [f"# {record.title}", "", record.summary]
    for heading, key in (("Problem", "problem"), ("Approach", "approach"), ("Why it fits", "why_it_fits")):
        value = s.get(key)
        if isinstance(value, str) and value.strip():
            out += ["", f"## {heading}", value.strip()]
    for heading, key in (("Components", "components"), ("Risks", "risks")):
        value = s.get(key)
        if isinstance(value, list):
            picked = [f"- {str(x).strip()}" for x in value if str(x).strip()]
            if picked:
                out += ["", f"## {heading}", *picked]
    rating = record.rating if record.rating is not None else "unrated"
    out += ["", f"`{record.idea_id}` · rating: {rating}"]
    return "\n".join(out)


def proposal_markdown(record: ProposalRecord) -> str:
    return "\n".join(
        [
            f"# Proposal `{record.proposal_id}`",
            "",
            describe_proposal(record),
            "",
            f"**Kind:** {record.kind}  ·  **Status:** {record.status}",
            "",
            "Press `a` to approve or `x` to reject.",
        ]
    )


def candidates_markdown(title: str, candidates: list[RelatedCandidate]) -> str:
    out = [f"# {title}", ""]
    for c in candidates:
        out += [f"### {c.title}", f"`{c.note_id}` · score {c.score:.2f}", "", c.summary or "", ""]
    return "\n".join(out)


def ask_markdown(question: str, answer: str, sources: list[RelatedCandidate]) -> str:
    out = [f"# {question}", "", answer]
    if sources:
        out += ["", "## Sources"] + [f"- `{c.note_id}` {c.title}" for c in sources]
    return "\n".join(out)


def status_markdown(info: StatusInfo) -> str:
    s = info.stats
    index = "not configured" if not info.index_configured else ("empty" if info.index_empty else "ready")
    return "\n".join(
        [
            "# Status",
            "",
            f"- **Notes:** {s.total}",
            f"- **LLM:** {s.llm_generated} generated, {s.llm_failed} failed, {s.llm_skipped} skipped",
            f"- **Embeddings:** {s.embedding_indexed} indexed, {s.embedding_failed} failed, {s.embedding_skipped} skipped",
            f"- **Index:** {index}",
            f"- **Pending proposals:** {info.pending_proposals}",
        ]
    )

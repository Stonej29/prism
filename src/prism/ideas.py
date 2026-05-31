from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from prism.db import IdeaRecord, PrismDatabase
from prism.index import NoteIndexer, RelatedCandidate
from prism.llm import LLMClient, LLMConfig, build_idea_context
from prism.notes import (
    _block_field,
    _json_array,
    _json_object,
    _list_or_text,
    _string_field,
    _tags,
    clean_title,
    ensure_profile,
    normalize_related_notes,
    slugify,
    tags_for_record,
)

KNOWLEDGE_LIMIT = 12
PAST_IDEAS_LIMIT = 10


@dataclass(frozen=True)
class IdeaResult:
    record: IdeaRecord | None
    ok: bool
    message: str


class IdeaService:
    def __init__(
        self,
        vault_path: Path,
        database: PrismDatabase,
        llm_config: LLMConfig | None = None,
        indexer: NoteIndexer | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.ideas_path = vault_path / "generated-ideas"
        self.profile_path = vault_path / "profile" / "personal.md"
        self.database = database
        self.llm_config = llm_config or LLMConfig("https://openrouter.ai/api/v1", None, None)
        self.indexer = indexer
        self.ideas_path.mkdir(parents=True, exist_ok=True)
        ensure_profile(self.profile_path)

    def generate_idea(self, topic: str | None = None, prefer_job: bool = False) -> IdeaResult:
        topic = (topic or "").strip() or None
        if not self.llm_config.is_configured:
            return IdeaResult(record=None, ok=False, message="Idea generation needs LLM_API_KEY and LLM_MODEL.")

        candidates = self._gather_knowledge(topic, prefer_job)
        created = datetime.now(UTC).replace(microsecond=0)
        created_at = created.isoformat().replace("+00:00", "Z")
        idea_id = self._new_idea_id()

        context = build_idea_context(
            topic=topic,
            knowledge=[candidate.to_llm_dict() for candidate in candidates],
            past_ideas=self._past_ideas(),
        )

        structured: dict[str, Any] = {}
        llm_status = "generated"
        llm_error: str | None = None
        llm_model: str | None = None
        try:
            generation = LLMClient(self.llm_config).generate_idea(context, self.profile_path.read_text(encoding="utf-8"))
            structured = self._normalize(generation.data, candidates)
            llm_model = generation.model
        except Exception as exc:
            llm_status = "failed"
            llm_error = f"{type(exc).__name__}: {exc}"[:1000]

        generated = llm_status == "generated"
        title = clean_title(_string_field(structured, "title")) or _fallback_title(topic)
        summary = _string_field(structured, "summary") or (
            "Generated project idea." if generated else "Idea generation failed."
        )
        tags = _tags(structured.get("tags"))
        source_ids = [candidate.note_id for candidate in candidates]

        filename = f"{created.date().isoformat()}-{slugify(title)}.md"
        note_path = self._unique_idea_path(filename)
        relative_note_path = str(note_path.relative_to(self.vault_path))

        record = IdeaRecord(
            idea_id=idea_id,
            created_at=created_at,
            title=title,
            summary=summary,
            topic=topic,
            note_path=relative_note_path,
            llm_status=llm_status,
            llm_error=llm_error,
            llm_model=llm_model,
            structured_json=json.dumps(structured, ensure_ascii=True, sort_keys=True) if structured else None,
            tags_json=json.dumps(tags, ensure_ascii=True),
            source_note_ids_json=json.dumps(source_ids, ensure_ascii=True),
        )
        note_path.write_text(render_idea(record), encoding="utf-8")
        self.database.insert_idea(record)

        if generated:
            return IdeaResult(record=record, ok=True, message=summary)
        return IdeaResult(record=record, ok=False, message=f"Idea generation failed: {llm_error}")

    def record_rating(self, idea_id: str, rating: int) -> IdeaRecord | None:
        record = self.database.find_by_idea_id(idea_id)
        if not record:
            return None
        rated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.database.update_idea_rating(idea_id, rating, rated_at)
        updated = replace(record, rating=rating, rated_at=rated_at)
        if updated.note_path:
            path = self.vault_path / updated.note_path
            try:
                path.write_text(render_idea(updated), encoding="utf-8")
            except OSError:
                pass
        return updated

    def delete_idea(self, idea_id: str) -> IdeaRecord | None:
        record = self.database.find_by_idea_id(idea_id.strip().lower())
        if not record:
            return None
        if record.note_path:
            path = self.vault_path / record.note_path
            try:
                resolved = path.resolve()
                base = self.vault_path.resolve()
                if resolved != base and base in resolved.parents and resolved.exists():
                    resolved.unlink()
            except OSError:
                pass
        self.database.delete_idea(record.idea_id)
        return record

    def _gather_knowledge(self, topic: str | None, prefer_job: bool = False) -> list[RelatedCandidate]:
        # Steered ideation: when asked to focus on the user's job, seed the
        # knowledge from notes they flagged as job-relevant (topped up with
        # semantic/recent candidates if there are few flagged notes).
        if prefer_job:
            job = self._job_candidates()
            if job:
                if len(job) >= KNOWLEDGE_LIMIT:
                    return job[:KNOWLEDGE_LIMIT]
                seen = {c.note_id for c in job}
                extra = self._gather_knowledge(topic, prefer_job=False)
                return (job + [c for c in extra if c.note_id not in seen])[:KNOWLEDGE_LIMIT]
        if topic and self.indexer and self.indexer.is_configured:
            try:
                results = self.indexer.search_text(topic, limit=KNOWLEDGE_LIMIT)
            except Exception:
                results = []
            if results:
                return results
        return self._recent_candidates()

    def _job_candidates(self) -> list[RelatedCandidate]:
        return [
            RelatedCandidate(
                note_id=record.note_id,
                title=record.title,
                summary=record.summary,
                note_path=record.note_path,
                source_url=record.source_url,
                tags=tags_for_record(record),
                score=0.0,
            )
            for record in self.database.list_job_notes(KNOWLEDGE_LIMIT)
            if record.llm_status == "generated"
        ]

    def _recent_candidates(self) -> list[RelatedCandidate]:
        candidates: list[RelatedCandidate] = []
        for record in self.database.list_recent_notes(40):
            if record.llm_status != "generated":
                continue
            candidates.append(
                RelatedCandidate(
                    note_id=record.note_id,
                    title=record.title,
                    summary=record.summary,
                    note_path=record.note_path,
                    source_url=record.source_url,
                    tags=tags_for_record(record),
                    score=0.0,
                )
            )
            if len(candidates) >= KNOWLEDGE_LIMIT:
                break
        return candidates

    def _past_ideas(self) -> list[dict[str, Any]]:
        return [
            {"title": idea.title, "summary": idea.summary, "rating": idea.rating}
            for idea in self.database.list_rated_ideas(PAST_IDEAS_LIMIT)
        ]

    def _normalize(self, data: dict[str, Any], candidates: list[RelatedCandidate]) -> dict[str, Any]:
        normalized = dict(data)
        normalized["tags"] = _tags(normalized.get("tags"))
        normalized["related_notes"] = normalize_related_notes(normalized.get("related_notes"), candidates)
        return normalized

    def _new_idea_id(self) -> str:
        while True:
            idea_id = secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:6].lower()
            if len(idea_id) == 6 and not self.database.idea_id_exists(idea_id):
                return idea_id

    def _unique_idea_path(self, filename: str) -> Path:
        path = self.ideas_path / filename
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        counter = 2
        while True:
            candidate = self.ideas_path / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1


def render_idea(record: IdeaRecord) -> str:
    structured = _json_object(record.structured_json)
    tags = _json_array(record.tags_json)
    source_ids = _json_array(record.source_note_ids_json)
    generated = record.llm_status == "generated"
    frontmatter = {
        "id": record.idea_id,
        "title": record.title,
        "type": "idea",
        "created": record.created_at,
        "topic": record.topic,
        "status": "rated" if record.rating is not None else "unrated",
        "rating": record.rating,
        "tags": tags,
        "source_notes": [str(item) for item in source_ids],
        "llm_status": record.llm_status,
        "llm_model": record.llm_model,
    }
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()

    if generated:
        body = (
            f"# {record.title}\n\n"
            f"{record.summary}\n\n"
            f"## Problem\n\n{_block_field(structured, 'problem')}\n\n"
            f"## Approach\n\n{_block_field(structured, 'approach')}\n\n"
            f"## Why It Fits\n\n{_block_field(structured, 'why_it_fits')}\n\n"
            f"## Components\n\n{_list_or_text(structured.get('components'))}\n\n"
            f"## Risks\n\n{_list_or_text(structured.get('risks'))}\n\n"
            f"## Related Notes\n\n{_idea_related_lines(structured.get('related_notes'))}\n\n"
            f"## Generated From\n\n{_generated_from_lines(source_ids)}\n"
        )
    else:
        llm_line = f"- LLM status: {record.llm_status}"
        if record.llm_error:
            llm_line += f" ({record.llm_error})"
        body = (
            f"# {record.title}\n\n"
            f"{record.summary}\n\n"
            f"## Generated From\n\n{_generated_from_lines(source_ids)}\n\n"
            f"## Notes\n\n{llm_line}\n"
        )
    return f"---\n{yaml_text}\n---\n\n{body}"


def _idea_related_lines(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "None selected."
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("id") or "").strip()
        if not title:
            continue
        stem = Path(item.get("path") or title).stem or str(item.get("id") or title)
        reason = str(item.get("reason") or "Related context.").strip()
        lines.append(f"- [[{stem}|{title}]] - {reason}")
    return "\n".join(lines) or "None selected."


def _generated_from_lines(source_ids: list[Any]) -> str:
    ids = [str(item).strip() for item in source_ids if str(item).strip()]
    if not ids:
        return "No source notes."
    return "\n".join(f"- {note_id}" for note_id in ids)


def _fallback_title(topic: str | None) -> str:
    if topic:
        return clean_title(f"Idea: {topic}") or "Untitled idea"
    return "Untitled idea"

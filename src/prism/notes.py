from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from prism.db import NoteRecord, PrismDatabase
from prism.fetch import FetchResult, extract_website_text, fetch_source
from prism.index import NoteIndexer, RelatedCandidate, canonical_index_text
from prism.llm import LLMClient, LLMConfig, build_llm_context

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
PREVIEW_LIMIT = 1500
SCORE_FIELDS = ("relevance", "novelty", "credibility", "actionability", "interest", "overall")
DEFAULT_PROFILE = """# Personal Profile

Jone is based in Copenhagen/Lyngby and studies a data science and machine learning master's at DTU. He works at HIVE Robotics on humanoid robot software.

Core interests: robotics, vision-language-action models, inverse kinematics and control, manipulation, perception, computer vision, agents, AI systems, open-source tools, practical research, and home tinkering on an Ubuntu server with an RTX 3090.

Prefer notes that are dense, practical, technical, and direct. Emphasize a healthy mix of buildable ideas, research novelty, and practical tool value.
"""


@dataclass(frozen=True)
class SaveResult:
    record: NoteRecord
    created: bool
    duplicate_reason: str | None = None


@dataclass(frozen=True)
class ReprocessResult:
    record: NoteRecord | None
    ok: bool
    message: str


class NoteService:
    def __init__(
        self,
        vault_path: Path,
        database: PrismDatabase,
        archive_path: Path,
        llm_config: LLMConfig | None = None,
        indexer: NoteIndexer | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.notes_path = vault_path / "notes"
        self.archive_path = archive_path
        self.profile_path = vault_path / "profile" / "personal.md"
        self.database = database
        self.llm_config = llm_config or LLMConfig("https://openrouter.ai/api/v1", None, None)
        self.indexer = indexer
        self.notes_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        ensure_profile(self.profile_path)

    def save_url(self, source_url: str) -> SaveResult:
        existing = self.database.find_by_source_url(source_url)
        if existing:
            return SaveResult(record=existing, created=False, duplicate_reason="source_url")

        saved_at = datetime.now(UTC).replace(microsecond=0)
        note_id = self._new_note_id()
        fetch = fetch_source(source_url, self.archive_path, note_id)

        duplicate = self.database.find_by_content_hash(fetch.content_hash)
        if duplicate:
            return SaveResult(record=duplicate, created=False, duplicate_reason="content_hash")

        title = clean_title(fetch.title) or placeholder_title(source_url)
        filename = f"{saved_at.date().isoformat()}-{slugify(title)}.md"
        note_path = self._unique_note_path(filename)
        relative_note_path = str(note_path.relative_to(self.vault_path))
        summary = summary_for_fetch(source_url, fetch)

        record = NoteRecord(
            note_id=note_id,
            source_url=source_url,
            resolved_url=fetch.resolved_url,
            note_path=relative_note_path,
            date_saved=saved_at.isoformat().replace("+00:00", "Z"),
            status="unreviewed",
            title=title,
            summary=summary,
            source_kind=fetch.source_kind,
            local_archive=fetch.local_archive,
            pdf_path=fetch.pdf_path,
            content_hash=fetch.content_hash,
            fetch_status=fetch.fetch_status,
            fetch_error=fetch.fetch_error,
            fetched_at=fetch.fetched_at,
            metadata_json=json.dumps(fetch.metadata, ensure_ascii=True, sort_keys=True),
        )
        record = self._apply_llm(record, fetch.extracted_text, fetch.metadata)
        note_path.write_text(render_note(record, fetch.extracted_text), encoding="utf-8")
        self.database.insert_note(record)
        record = self._index_after_persist(record)
        return SaveResult(record=record, created=True)

    def reprocess(self, note_id: str) -> ReprocessResult:
        record = self.database.find_by_note_id(note_id.strip().lower())
        if not record:
            return ReprocessResult(record=None, ok=False, message=f"No note found for {note_id}.")
        if record.fetch_status != "fetched":
            return ReprocessResult(record=record, ok=False, message=f"Cannot reprocess {record.note_id}: fetch status is {record.fetch_status}.")
        if not record.local_archive:
            return ReprocessResult(record=record, ok=False, message=f"Cannot reprocess {record.note_id}: no local archive recorded.")

        extracted_path = Path(record.local_archive) / "extracted.txt"
        if not extracted_path.exists():
            return ReprocessResult(record=record, ok=False, message=f"Cannot reprocess {record.note_id}: archived extracted.txt is missing.")

        extracted_text = extracted_path.read_text(encoding="utf-8")
        metadata = _json_object(record.metadata_json)
        if not extracted_text.strip() and record.local_archive:
            raw_path = Path(record.local_archive) / "raw.html"
            if raw_path.exists():
                _, recovered_text, recovered_metadata = extract_website_text(
                    raw_path.read_text(encoding="utf-8"),
                    record.resolved_url or record.source_url,
                    Path(record.local_archive),
                )
                if recovered_text.strip():
                    extracted_text = recovered_text
                    extracted_path.write_text(extracted_text, encoding="utf-8")
                    metadata = {**metadata, **recovered_metadata}
                    record = replace(record, metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True))
        updated = self._apply_llm(record, extracted_text, metadata, force=True)
        note_path = self.vault_path / updated.note_path
        note_path.write_text(render_note(updated, extracted_text), encoding="utf-8")
        self.database.update_note(updated)
        updated = self._index_after_persist(updated)
        if updated.llm_status == "generated":
            return ReprocessResult(record=updated, ok=True, message=f"Reprocessed: {updated.title}")
        return ReprocessResult(record=updated, ok=False, message=f"LLM {updated.llm_status}: {updated.llm_error or 'not generated'}")

    def _apply_llm(self, record: NoteRecord, extracted_text: str, metadata: dict[str, Any], force: bool = False) -> NoteRecord:
        if record.fetch_status != "fetched":
            return replace(record, llm_status="skipped", llm_error="fetch did not succeed")
        if not self.llm_config.is_configured:
            return replace(record, llm_status="skipped", llm_error="LLM_API_KEY or LLM_MODEL is not configured")
        if not extracted_text.strip():
            return replace(record, llm_status="skipped", llm_error="no extracted text available")

        try:
            related_candidates = self._related_candidates(record, extracted_text)
            context = build_llm_context(
                title=record.title,
                source_kind=record.source_kind,
                source_url=record.source_url,
                resolved_url=record.resolved_url,
                fetched_at=record.fetched_at,
                fetch_status=record.fetch_status,
                fetch_error=record.fetch_error,
                metadata=metadata,
                extracted_text=extracted_text,
                related_candidates=[candidate.to_llm_dict() for candidate in related_candidates],
            )
            generation = LLMClient(self.llm_config).generate_note(context, self.profile_path.read_text(encoding="utf-8"))
            structured = normalize_structured_summary(generation.data, related_candidates)
            title = clean_title(_string_field(structured, "title")) or record.title
            summary = _string_field(structured, "quick_summary") or record.summary
            tags = _tags(structured.get("tags"))
            scores = _scores(structured)
            generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            return replace(
                record,
                title=title,
                summary=summary,
                llm_status="generated",
                llm_error=None,
                llm_generated_at=generated_at,
                llm_model=generation.model,
                tags_json=json.dumps(tags, ensure_ascii=True),
                scores_json=json.dumps(scores, ensure_ascii=True, sort_keys=True),
                structured_summary_json=json.dumps(structured, ensure_ascii=True, sort_keys=True),
                related_notes_json=json.dumps(structured.get("related_notes", []), ensure_ascii=True, sort_keys=True),
            )
        except Exception as exc:
            if force or record.llm_status != "generated":
                return replace(record, llm_status="failed", llm_error=f"{type(exc).__name__}: {exc}"[:1000])
            return record

    def _related_candidates(self, record: NoteRecord, extracted_text: str) -> list[RelatedCandidate]:
        if not self.indexer or not self.indexer.is_configured:
            return []
        query = f"{canonical_index_text(record)}\nExtracted text: {extracted_preview(extracted_text)[:8000]}"
        try:
            return self.indexer.search_text(query, limit=10, exclude_note_id=record.note_id)
        except Exception:
            return []

    def _index_after_persist(self, record: NoteRecord) -> NoteRecord:
        if not self.indexer:
            return record
        result = self.indexer.index_record(record, self.database)
        return replace(
            record,
            embedding_status=result.status,
            embedding_error=result.error,
            embedded_at=result.embedded_at,
            embedding_model=result.model,
            embedding_dimensions=result.dimensions,
            embedding_text_hash=result.text_hash,
        )

    def _new_note_id(self) -> str:
        while True:
            note_id = secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:6].lower()
            if len(note_id) == 6 and not self.database.note_id_exists(note_id):
                return note_id

    def _unique_note_path(self, filename: str) -> Path:
        path = self.notes_path / filename
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        counter = 2
        while True:
            candidate = self.notes_path / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1


def ensure_profile(profile_path: Path) -> None:
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if not profile_path.exists():
        profile_path.write_text(DEFAULT_PROFILE, encoding="utf-8")


def extract_first_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)\"]}'")


def placeholder_title(source_url: str) -> str:
    parsed = urlparse(source_url)
    host = parsed.netloc or "unknown-source"
    path_part = Path(parsed.path).stem if parsed.path else ""
    readable_path = slugify(path_part).replace("-", " ").strip()
    if readable_path:
        return f"Placeholder: {host} / {readable_path}"
    return f"Placeholder: {host}"


def clean_title(value: str | None) -> str | None:
    if not value:
        return None
    title = re.sub(r"\s+", " ", value).strip()
    return title[:200] if title else None


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:80] or "placeholder-title"


def summary_for_fetch(source_url: str, fetch: FetchResult) -> str:
    if fetch.fetch_status == "fetched":
        return f"Fetched {fetch.source_kind} capture for {source_url}"
    return f"Fetch failed for {source_url}: {fetch.fetch_error or 'unknown error'}"


def render_note(record: NoteRecord, extracted_text: str = "") -> str:
    structured = structured_summary(record)
    tags = tags_for_record(record)
    scores = scores_for_record(record)
    generated = record.llm_status == "generated"
    frontmatter = {
        "id": record.note_id,
        "title": record.title,
        "type": "source",
        "source_url": record.source_url,
        "resolved_url": record.resolved_url,
        "date_saved": record.date_saved,
        "date_processed": record.fetched_at,
        "source_kind": record.source_kind,
        "local_archive": record.local_archive,
        "pdf_path": record.pdf_path,
        "content_hash": record.content_hash,
        "fetch_status": record.fetch_status,
        "fetch_error": record.fetch_error,
        "llm_status": record.llm_status,
        "llm_error": record.llm_error,
        "llm_generated_at": record.llm_generated_at,
        "llm_model": record.llm_model,
        "confidence": structured.get("confidence") if generated else None,
        "status": record.status,
        "tags": tags,
        "relevance_score": scores.get("relevance"),
        "novelty_score": scores.get("novelty"),
        "credibility_score": scores.get("credibility"),
        "actionability_score": scores.get("actionability"),
        "interest_score": scores.get("interest"),
        "overall_score": scores.get("overall"),
        "summary_status": "generated" if generated else "placeholder",
        "related_notes": [item["id"] for item in related_notes_for_record(record)],
    }
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()

    if generated:
        body = render_generated_body(record, structured, extracted_text)
    else:
        body = render_fallback_body(record, extracted_text)
    return f"---\n{yaml_text}\n---\n\n{body}"


def render_generated_body(record: NoteRecord, structured: dict[str, Any], extracted_text: str) -> str:
    preview = extracted_preview(extracted_text) or "No extracted text available."
    return (
        f"# {record.title}\n\n"
        f"{_string_field(structured, 'quick_summary') or record.summary}\n\n"
        f"## Detailed Summary\n\n{_block_field(structured, 'detailed_summary')}\n\n"
        f"## Key Claims\n\n{_list_or_text(structured.get('key_claims'))}\n\n"
        f"## Limitations and Caveats\n\n{_list_or_text(structured.get('limitations'))}\n\n"
        f"## Technical Details\n\n{_list_or_text(structured.get('technical_details'))}\n\n"
        f"## Why It Matters\n\n{_block_field(structured, 'why_it_matters')}\n\n"
        f"## Personal Relevance\n\n{_block_field(structured, 'personal_relevance')}\n\n"
        f"## Possible Project Ideas\n\n{_list_or_text(structured.get('project_ideas'))}\n\n"
        f"## Related Notes\n\n{_related_note_lines(record)}\n\n"
        f"## Source\n\n{_source_lines(record)}\n\n"
        f"## Archive\n\n{_archive_lines(record)}\n\n"
        f"## Extracted Text Preview\n\n{preview}\n"
    )


def render_fallback_body(record: NoteRecord, extracted_text: str) -> str:
    preview = extracted_preview(extracted_text) or "No extracted text available."
    llm_line = f"- LLM status: {record.llm_status}"
    if record.llm_error:
        llm_line += f" ({record.llm_error})"
    return (
        f"# {record.title}\n\n"
        f"{record.summary}\n\n"
        f"## Source\n\n{_source_lines(record)}\n\n"
        f"## Archive\n\n{_archive_lines(record)}\n\n"
        f"## Extracted Text Preview\n\n{preview}\n\n"
        f"## Notes\n\n{llm_line}\n"
    )


def structured_summary(record: NoteRecord) -> dict[str, Any]:
    return _json_object(record.structured_summary_json)


def tags_for_record(record: NoteRecord) -> list[str]:
    data = _json_array(record.tags_json)
    return _tags(data)


def scores_for_record(record: NoteRecord) -> dict[str, float | int]:
    data = _json_object(record.scores_json)
    return _scores(data)


def more_summary_for_record(record: NoteRecord) -> str:
    structured = structured_summary(record)
    return _string_field(structured, "detailed_summary") or record.summary


def normalize_structured_summary(data: dict[str, Any], related_candidates: list[RelatedCandidate] | None = None) -> dict[str, Any]:
    normalized = dict(data)
    normalized["tags"] = _tags(normalized.get("tags"))
    normalized["related_notes"] = normalize_related_notes(normalized.get("related_notes"), related_candidates or [])
    for key, value in _scores(normalized).items():
        normalized[key] = value
    return normalized


def normalize_related_notes(value: Any, related_candidates: list[RelatedCandidate] | None = None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    candidates = {candidate.note_id: candidate for candidate in (related_candidates or [])}
    related: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id") or item.get("note_id") or "").strip().lower()
        if not note_id or note_id in seen:
            continue
        candidate = candidates.get(note_id)
        title = _clean_related_text(item.get("title")) or (candidate.title if candidate else note_id)
        reason = _clean_related_text(item.get("reason")) or "Related context."
        path = candidate.note_path if candidate else ""
        related.append({"id": note_id, "title": title, "reason": reason, "path": path})
        seen.add(note_id)
    return related[:10]


def related_notes_for_record(record: NoteRecord) -> list[dict[str, str]]:
    data = _json_array(record.related_notes_json)
    normalized: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or note_id).strip()
        reason = str(item.get("reason") or "Related context.").strip()
        path = str(item.get("path") or "").strip()
        if note_id:
            normalized.append({"id": note_id, "title": title, "reason": reason, "path": path})
    return normalized


def extracted_preview(text: str) -> str:
    preview = re.sub(r"\s+", " ", text).strip()
    if len(preview) > PREVIEW_LIMIT:
        return preview[:PREVIEW_LIMIT].rstrip() + "..."
    return preview


def _related_note_lines(record: NoteRecord) -> str:
    items = related_notes_for_record(record)
    if not items:
        return "None selected."
    lines: list[str] = []
    for item in items:
        stem = Path(item.get("path") or item["title"]).stem or item["id"]
        lines.append(f"- [[{stem}|{item['title']}]] - {item['reason']}")
    return "\n".join(lines)


def _clean_related_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:300]


def _source_lines(record: NoteRecord) -> str:
    return (
        f"- URL: {record.source_url}\n"
        f"- Resolved URL: {record.resolved_url}\n"
        f"- Saved: {record.date_saved}\n"
        f"- Fetched: {record.fetched_at or 'Not fetched'}"
    )


def _archive_lines(record: NoteRecord) -> str:
    lines = [
        f"- Local archive: {record.local_archive or 'None'}",
        f"- PDF: {record.pdf_path or 'None'}",
        f"- Content hash: {record.content_hash or 'None'}",
        f"- Fetch status: {record.fetch_status}",
    ]
    if record.fetch_error:
        lines.append(f"- Fetch error: {record.fetch_error}")
    return "\n".join(lines)


def _string_field(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def _block_field(data: dict[str, Any], key: str) -> str:
    return _string_field(data, key) or "Not provided."


def _list_or_text(value: Any) -> str:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(f"- {item}" for item in items) or "Not provided."
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "Not provided."


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = re.sub(r"[^a-z0-9-]+", "-", str(item).lower().lstrip("#")).strip("-")
        if tag and tag not in tags:
            tags.append(tag[:50])
    return tags[:12]


def _scores(data: dict[str, Any]) -> dict[str, float | int]:
    scores: dict[str, float | int] = {}
    for key in SCORE_FIELDS:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            scores[key] = value
        elif isinstance(value, str):
            try:
                scores[key] = float(value)
            except ValueError:
                pass
    return scores


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_array(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


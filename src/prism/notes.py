from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from prism.db import NoteRecord, PrismDatabase
from prism.fetch import FetchResult, fetch_source

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
PREVIEW_LIMIT = 3000


@dataclass(frozen=True)
class SaveResult:
    record: NoteRecord
    created: bool
    duplicate_reason: str | None = None


class NoteService:
    def __init__(self, vault_path: Path, database: PrismDatabase, archive_path: Path) -> None:
        self.vault_path = vault_path
        self.notes_path = vault_path / "notes"
        self.archive_path = archive_path
        self.database = database
        self.notes_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)

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

        note_path.write_text(render_note(record, fetch.extracted_text), encoding="utf-8")
        self.database.insert_note(record)
        return SaveResult(record=record, created=True)

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
        "confidence": None,
        "status": record.status,
        "tags": [],
        "relevance_score": None,
        "novelty_score": None,
        "credibility_score": None,
        "actionability_score": None,
        "interest_score": None,
        "overall_score": None,
        "summary_status": "placeholder",
        "llm_model": None,
    }
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()
    archive_lines = [
        f"- Local archive: {record.local_archive or 'None'}",
        f"- PDF: {record.pdf_path or 'None'}",
        f"- Content hash: {record.content_hash or 'None'}",
        f"- Fetch status: {record.fetch_status}",
    ]
    if record.fetch_error:
        archive_lines.append(f"- Fetch error: {record.fetch_error}")

    preview = extracted_preview(extracted_text)
    if not preview:
        preview = "No extracted text available."

    return (
        f"---\n{yaml_text}\n---\n\n"
        f"# {record.title}\n\n"
        f"{record.summary}\n\n"
        "## Source\n\n"
        f"- URL: {record.source_url}\n"
        f"- Resolved URL: {record.resolved_url}\n"
        f"- Saved: {record.date_saved}\n"
        f"- Fetched: {record.fetched_at or 'Not fetched'}\n\n"
        "## Archive\n\n"
        + "\n".join(archive_lines)
        + "\n\n"
        "## Extracted Text Preview\n\n"
        f"{preview}\n\n"
        "## Notes\n\n"
        "- LLM processing has not run yet.\n"
    )


def extracted_preview(text: str) -> str:
    preview = re.sub(r"\s+", " ", text).strip()
    if len(preview) > PREVIEW_LIMIT:
        return preview[:PREVIEW_LIMIT].rstrip() + "..."
    return preview

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from prism.db import NoteRecord, PrismDatabase

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


@dataclass(frozen=True)
class SaveResult:
    record: NoteRecord
    created: bool


class NoteService:
    def __init__(self, vault_path: Path, database: PrismDatabase) -> None:
        self.vault_path = vault_path
        self.notes_path = vault_path / "notes"
        self.database = database
        self.notes_path.mkdir(parents=True, exist_ok=True)

    def save_url(self, source_url: str) -> SaveResult:
        existing = self.database.find_by_source_url(source_url)
        if existing:
            return SaveResult(record=existing, created=False)

        saved_at = datetime.now(UTC).replace(microsecond=0)
        note_id = self._new_note_id()
        title = placeholder_title(source_url)
        filename = f"{saved_at.date().isoformat()}-{slugify(title)}.md"
        note_path = self._unique_note_path(filename)
        relative_note_path = str(note_path.relative_to(self.vault_path))
        summary = f"Placeholder capture for {source_url}"

        record = NoteRecord(
            note_id=note_id,
            source_url=source_url,
            resolved_url=source_url,
            note_path=relative_note_path,
            date_saved=saved_at.isoformat().replace("+00:00", "Z"),
            status="unreviewed",
            title=title,
            summary=summary,
        )

        note_path.write_text(render_note(record), encoding="utf-8")
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


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:80] or "placeholder-title"


def render_note(record: NoteRecord) -> str:
    frontmatter = {
        "id": record.note_id,
        "title": record.title,
        "type": "source",
        "source_url": record.source_url,
        "resolved_url": record.resolved_url,
        "date_saved": record.date_saved,
        "date_processed": None,
        "source_kind": "unknown",
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
    return (
        f"---\n{yaml_text}\n---\n\n"
        f"# {record.title}\n\n"
        f"{record.summary}\n\n"
        "## Source\n\n"
        f"- URL: {record.source_url}\n"
        f"- Saved: {record.date_saved}\n\n"
        "## Notes\n\n"
        "- Processing has not run yet.\n"
    )

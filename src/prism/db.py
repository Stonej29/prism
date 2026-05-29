from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NoteRecord:
    note_id: str
    source_url: str
    resolved_url: str
    note_path: str
    date_saved: str
    status: str
    title: str
    summary: str
    source_kind: str = "unknown"
    local_archive: str | None = None
    pdf_path: str | None = None
    content_hash: str | None = None
    fetch_status: str = "not_fetched"
    fetch_error: str | None = None
    fetched_at: str | None = None
    metadata_json: str | None = None
    llm_status: str = "skipped"
    llm_error: str | None = None
    llm_generated_at: str | None = None
    llm_model: str | None = None
    tags_json: str | None = None
    scores_json: str | None = None
    structured_summary_json: str | None = None


class PrismDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def find_by_source_url(self, source_url: str) -> NoteRecord | None:
        with self.connect() as conn:
            row = conn.execute(f"""
                SELECT {_NOTE_COLUMNS}
                FROM notes
                WHERE source_url = ?
                """,
                (source_url,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def find_by_content_hash(self, content_hash: str | None) -> NoteRecord | None:
        if not content_hash:
            return None
        with self.connect() as conn:
            row = conn.execute(f"""
                SELECT {_NOTE_COLUMNS}
                FROM notes
                WHERE content_hash = ? AND content_hash IS NOT NULL AND content_hash != ''
                ORDER BY date_saved ASC
                LIMIT 1
                """,
                (content_hash,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def find_by_note_id(self, note_id: str) -> NoteRecord | None:
        with self.connect() as conn:
            row = conn.execute(f"""
                SELECT {_NOTE_COLUMNS}
                FROM notes
                WHERE note_id = ?
                """,
                (note_id,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def insert_note(self, record: NoteRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notes (
                    note_id, source_url, resolved_url, note_path, date_saved, status, title, summary,
                    source_kind, local_archive, pdf_path, content_hash, fetch_status, fetch_error,
                    fetched_at, metadata_json, llm_status, llm_error, llm_generated_at, llm_model,
                    tags_json, scores_json, structured_summary_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.note_id,
                    record.source_url,
                    record.resolved_url,
                    record.note_path,
                    record.date_saved,
                    record.status,
                    record.title,
                    record.summary,
                    record.source_kind,
                    record.local_archive,
                    record.pdf_path,
                    record.content_hash,
                    record.fetch_status,
                    record.fetch_error,
                    record.fetched_at,
                    record.metadata_json,
                    record.llm_status,
                    record.llm_error,
                    record.llm_generated_at,
                    record.llm_model,
                    record.tags_json,
                    record.scores_json,
                    record.structured_summary_json,
                ),
            )

    def update_note(self, record: NoteRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE notes
                SET source_url = ?, resolved_url = ?, note_path = ?, date_saved = ?, status = ?,
                    title = ?, summary = ?, source_kind = ?, local_archive = ?, pdf_path = ?,
                    content_hash = ?, fetch_status = ?, fetch_error = ?, fetched_at = ?,
                    metadata_json = ?, llm_status = ?, llm_error = ?, llm_generated_at = ?,
                    llm_model = ?, tags_json = ?, scores_json = ?, structured_summary_json = ?
                WHERE note_id = ?
                """,
                (
                    record.source_url,
                    record.resolved_url,
                    record.note_path,
                    record.date_saved,
                    record.status,
                    record.title,
                    record.summary,
                    record.source_kind,
                    record.local_archive,
                    record.pdf_path,
                    record.content_hash,
                    record.fetch_status,
                    record.fetch_error,
                    record.fetched_at,
                    record.metadata_json,
                    record.llm_status,
                    record.llm_error,
                    record.llm_generated_at,
                    record.llm_model,
                    record.tags_json,
                    record.scores_json,
                    record.structured_summary_json,
                    record.note_id,
                ),
            )

    def note_id_exists(self, note_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM notes WHERE note_id = ?", (note_id,)).fetchone()
        return row is not None

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    note_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL UNIQUE,
                    resolved_url TEXT NOT NULL,
                    note_path TEXT NOT NULL,
                    date_saved TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            _add_missing_columns(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notes_content_hash
                ON notes(content_hash)
                WHERE content_hash IS NOT NULL AND content_hash != ''
                """
            )


_NOTE_COLUMNS = """
    note_id, source_url, resolved_url, note_path, date_saved, status, title, summary,
    source_kind, local_archive, pdf_path, content_hash, fetch_status, fetch_error, fetched_at, metadata_json,
    llm_status, llm_error, llm_generated_at, llm_model, tags_json, scores_json, structured_summary_json
"""

_ADDED_COLUMNS = {
    "source_kind": "TEXT NOT NULL DEFAULT 'unknown'",
    "local_archive": "TEXT",
    "pdf_path": "TEXT",
    "content_hash": "TEXT",
    "fetch_status": "TEXT NOT NULL DEFAULT 'not_fetched'",
    "fetch_error": "TEXT",
    "fetched_at": "TEXT",
    "metadata_json": "TEXT",
    "llm_status": "TEXT NOT NULL DEFAULT 'skipped'",
    "llm_error": "TEXT",
    "llm_generated_at": "TEXT",
    "llm_model": "TEXT",
    "tags_json": "TEXT",
    "scores_json": "TEXT",
    "structured_summary_json": "TEXT",
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(notes)")}
    for column, definition in _ADDED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE notes ADD COLUMN {column} {definition}")


def _row_to_record(row: sqlite3.Row) -> NoteRecord:
    return NoteRecord(
        note_id=row["note_id"],
        source_url=row["source_url"],
        resolved_url=row["resolved_url"],
        note_path=row["note_path"],
        date_saved=row["date_saved"],
        status=row["status"],
        title=row["title"],
        summary=row["summary"],
        source_kind=row["source_kind"],
        local_archive=row["local_archive"],
        pdf_path=row["pdf_path"],
        content_hash=row["content_hash"],
        fetch_status=row["fetch_status"],
        fetch_error=row["fetch_error"],
        fetched_at=row["fetched_at"],
        metadata_json=row["metadata_json"],
        llm_status=row["llm_status"],
        llm_error=row["llm_error"],
        llm_generated_at=row["llm_generated_at"],
        llm_model=row["llm_model"],
        tags_json=row["tags_json"],
        scores_json=row["scores_json"],
        structured_summary_json=row["structured_summary_json"],
    )

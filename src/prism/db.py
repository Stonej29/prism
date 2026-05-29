from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NoteStats:
    total: int
    llm_generated: int
    llm_failed: int
    llm_skipped: int
    embedding_indexed: int
    embedding_failed: int
    embedding_skipped: int


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
    embedding_status: str = "skipped"
    embedding_error: str | None = None
    embedded_at: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_text_hash: str | None = None
    related_notes_json: str | None = None


@dataclass(frozen=True)
class IdeaRecord:
    idea_id: str
    created_at: str
    title: str
    summary: str
    topic: str | None = None
    note_path: str | None = None
    llm_status: str = "skipped"
    llm_error: str | None = None
    llm_model: str | None = None
    structured_json: str | None = None
    tags_json: str | None = None
    source_note_ids_json: str | None = None
    rating: int | None = None
    rated_at: str | None = None


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
                    tags_json, scores_json, structured_summary_json, embedding_status, embedding_error,
                    embedded_at, embedding_model, embedding_dimensions, embedding_text_hash, related_notes_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    record.embedding_status,
                    record.embedding_error,
                    record.embedded_at,
                    record.embedding_model,
                    record.embedding_dimensions,
                    record.embedding_text_hash,
                    record.related_notes_json,
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
                    llm_model = ?, tags_json = ?, scores_json = ?, structured_summary_json = ?,
                    embedding_status = ?, embedding_error = ?, embedded_at = ?, embedding_model = ?,
                    embedding_dimensions = ?, embedding_text_hash = ?, related_notes_json = ?
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
                    record.embedding_status,
                    record.embedding_error,
                    record.embedded_at,
                    record.embedding_model,
                    record.embedding_dimensions,
                    record.embedding_text_hash,
                    record.related_notes_json,
                    record.note_id,
                ),
            )

    def list_failed_notes(self, limit: int = 25) -> list[NoteRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE llm_status = 'failed' OR embedding_status = 'failed'
                    ORDER BY date_saved ASC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def delete_note(self, note_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
        return cursor.rowcount > 0

    def delete_idea(self, idea_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM ideas WHERE idea_id = ?", (idea_id,))
        return cursor.rowcount > 0

    def delete_all(self) -> tuple[int, int]:
        with self.connect() as conn:
            note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] or 0
            idea_count = conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] or 0
            conn.execute("DELETE FROM notes")
            conn.execute("DELETE FROM ideas")
        return int(note_count), int(idea_count)

    def list_notes_for_reindexing(self) -> list[NoteRecord]:
        with self.connect() as conn:
            rows = conn.execute(f"""
                SELECT {_NOTE_COLUMNS}
                FROM notes
                ORDER BY date_saved ASC
                """).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_recent_notes(self, limit: int, offset: int = 0) -> list[NoteRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {_NOTE_COLUMNS} FROM notes ORDER BY date_saved DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_tags_with_counts(self) -> list[tuple[str, int]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT tags_json FROM notes WHERE llm_status = 'generated' AND tags_json IS NOT NULL"
            ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            try:
                tags = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str) and tag:
                        counts[tag] = counts.get(tag, 0) + 1
        return sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    def get_note_stats(self) -> NoteStats:
        with self.connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN llm_status = 'generated' THEN 1 ELSE 0 END) as llm_generated,
                    SUM(CASE WHEN llm_status = 'failed' THEN 1 ELSE 0 END) as llm_failed,
                    SUM(CASE WHEN llm_status = 'skipped' THEN 1 ELSE 0 END) as llm_skipped,
                    SUM(CASE WHEN embedding_status = 'indexed' THEN 1 ELSE 0 END) as embedding_indexed,
                    SUM(CASE WHEN embedding_status = 'failed' THEN 1 ELSE 0 END) as embedding_failed,
                    SUM(CASE WHEN embedding_status = 'skipped' THEN 1 ELSE 0 END) as embedding_skipped
                FROM notes
            """).fetchone()
        return NoteStats(
            total=row["total"] or 0,
            llm_generated=row["llm_generated"] or 0,
            llm_failed=row["llm_failed"] or 0,
            llm_skipped=row["llm_skipped"] or 0,
            embedding_indexed=row["embedding_indexed"] or 0,
            embedding_failed=row["embedding_failed"] or 0,
            embedding_skipped=row["embedding_skipped"] or 0,
        )

    def list_notes_by_tag(self, tag: str, limit: int, offset: int = 0) -> list[NoteRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE llm_status = 'generated' AND tags_json LIKE ?
                    ORDER BY date_saved DESC LIMIT ? OFFSET ?""",
                (f'%"{tag}"%', limit, offset),
            ).fetchall()
        records = [_row_to_record(row) for row in rows]
        return [r for r in records if tag in _parse_tags_json(r.tags_json)]

    def search_notes_keyword(self, query: str, limit: int) -> list[NoteRecord]:
        terms = _keyword_terms(query)
        if not terms or limit <= 0:
            return []
        where = " AND ".join(
            """(
                lower(title) LIKE ?
                OR lower(summary) LIKE ?
                OR lower(source_url) LIKE ?
                OR lower(COALESCE(tags_json, '')) LIKE ?
                OR lower(COALESCE(structured_summary_json, '')) LIKE ?
            )"""
            for _ in terms
        )
        params: list[str | int] = []
        for term in terms:
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern, pattern, pattern])
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE {where}
                    ORDER BY
                        CASE WHEN llm_status = 'generated' THEN 0 ELSE 1 END,
                        date_saved DESC
                    LIMIT ?""",
                params,
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def update_embedding_metadata(
        self,
        note_id: str,
        *,
        embedding_status: str,
        embedding_error: str | None = None,
        embedded_at: str | None = None,
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
        embedding_text_hash: str | None = None,
        related_notes_json: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE notes
                SET embedding_status = ?, embedding_error = ?, embedded_at = ?, embedding_model = ?,
                    embedding_dimensions = ?, embedding_text_hash = ?, related_notes_json = COALESCE(?, related_notes_json)
                WHERE note_id = ?
                """,
                (
                    embedding_status,
                    embedding_error,
                    embedded_at,
                    embedding_model,
                    embedding_dimensions,
                    embedding_text_hash,
                    related_notes_json,
                    note_id,
                ),
            )

    def update_related_notes(self, note_id: str, related_notes_json: str | None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE notes SET related_notes_json = ? WHERE note_id = ?", (related_notes_json, note_id))

    def note_id_exists(self, note_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM notes WHERE note_id = ?", (note_id,)).fetchone()
        return row is not None

    def insert_idea(self, record: IdeaRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ideas (
                    idea_id, created_at, title, summary, topic, note_path, llm_status, llm_error,
                    llm_model, structured_json, tags_json, source_note_ids_json, rating, rated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.idea_id,
                    record.created_at,
                    record.title,
                    record.summary,
                    record.topic,
                    record.note_path,
                    record.llm_status,
                    record.llm_error,
                    record.llm_model,
                    record.structured_json,
                    record.tags_json,
                    record.source_note_ids_json,
                    record.rating,
                    record.rated_at,
                ),
            )

    def find_by_idea_id(self, idea_id: str) -> IdeaRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT {_IDEA_COLUMNS} FROM ideas WHERE idea_id = ?",
                (idea_id,),
            ).fetchone()
        return _row_to_idea(row) if row else None

    def update_idea_rating(self, idea_id: str, rating: int, rated_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE ideas SET rating = ?, rated_at = ? WHERE idea_id = ?",
                (rating, rated_at, idea_id),
            )

    def list_recent_ideas(self, limit: int, offset: int = 0) -> list[IdeaRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {_IDEA_COLUMNS} FROM ideas ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_to_idea(row) for row in rows]

    def list_rated_ideas(self, limit: int) -> list[IdeaRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_IDEA_COLUMNS} FROM ideas
                    WHERE rating IS NOT NULL
                    ORDER BY rating DESC, rated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_row_to_idea(row) for row in rows]

    def idea_id_exists(self, idea_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM ideas WHERE idea_id = ?", (idea_id,)).fetchone()
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ideas (
                    idea_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            _add_missing_idea_columns(conn)


_NOTE_COLUMNS = """
    note_id, source_url, resolved_url, note_path, date_saved, status, title, summary,
    source_kind, local_archive, pdf_path, content_hash, fetch_status, fetch_error, fetched_at, metadata_json,
    llm_status, llm_error, llm_generated_at, llm_model, tags_json, scores_json, structured_summary_json,
    embedding_status, embedding_error, embedded_at, embedding_model, embedding_dimensions,
    embedding_text_hash, related_notes_json
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
    "embedding_status": "TEXT NOT NULL DEFAULT 'skipped'",
    "embedding_error": "TEXT",
    "embedded_at": "TEXT",
    "embedding_model": "TEXT",
    "embedding_dimensions": "INTEGER",
    "embedding_text_hash": "TEXT",
    "related_notes_json": "TEXT",
}


_IDEA_COLUMNS = """
    idea_id, created_at, title, summary, topic, note_path, llm_status, llm_error,
    llm_model, structured_json, tags_json, source_note_ids_json, rating, rated_at
"""

_IDEA_ADDED_COLUMNS = {
    "topic": "TEXT",
    "note_path": "TEXT",
    "llm_status": "TEXT NOT NULL DEFAULT 'skipped'",
    "llm_error": "TEXT",
    "llm_model": "TEXT",
    "structured_json": "TEXT",
    "tags_json": "TEXT",
    "source_note_ids_json": "TEXT",
    "rating": "INTEGER",
    "rated_at": "TEXT",
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(notes)")}
    for column, definition in _ADDED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE notes ADD COLUMN {column} {definition}")


def _add_missing_idea_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
    for column, definition in _IDEA_ADDED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE ideas ADD COLUMN {column} {definition}")


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
        embedding_status=row["embedding_status"],
        embedding_error=row["embedding_error"],
        embedded_at=row["embedded_at"],
        embedding_model=row["embedding_model"],
        embedding_dimensions=row["embedding_dimensions"],
        embedding_text_hash=row["embedding_text_hash"],
        related_notes_json=row["related_notes_json"],
    )


def _row_to_idea(row: sqlite3.Row) -> IdeaRecord:
    return IdeaRecord(
        idea_id=row["idea_id"],
        created_at=row["created_at"],
        title=row["title"],
        summary=row["summary"],
        topic=row["topic"],
        note_path=row["note_path"],
        llm_status=row["llm_status"],
        llm_error=row["llm_error"],
        llm_model=row["llm_model"],
        structured_json=row["structured_json"],
        tags_json=row["tags_json"],
        source_note_ids_json=row["source_note_ids_json"],
        rating=row["rating"],
        rated_at=row["rated_at"],
    )


def _parse_tags_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _keyword_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in query.lower().replace("_", " ").split():
        term = "".join(ch for ch in raw if ch.isalnum() or ch == "-").strip("-")
        if len(term) >= 3 and term not in terms:
            terms.append(term)
    return terms[:8]

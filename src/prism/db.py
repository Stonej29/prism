from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
    unreviewed: int = 0
    reviewed: int = 0
    archived: int = 0
    inbox: int = 0


@dataclass(frozen=True)
class TokenUsage:
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    today_total_tokens: int = 0
    today_calls: int = 0


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
    input_source: str = "unknown"
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
    favorite: int = 0
    purpose: str | None = None
    date_reviewed: str | None = None


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


@dataclass(frozen=True)
class ProposalRecord:
    proposal_id: str
    created_at: str
    kind: str
    status: str = "pending"
    note_ids_json: str | None = None
    payload_json: str | None = None
    resolved_at: str | None = None


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

    def find_by_resolved_url(self, resolved_url: str | None) -> NoteRecord | None:
        if not resolved_url:
            return None
        with self.connect() as conn:
            row = conn.execute(f"""
                SELECT {_NOTE_COLUMNS}
                FROM notes
                WHERE resolved_url = ? AND resolved_url IS NOT NULL AND resolved_url != ''
                ORDER BY date_saved ASC
                LIMIT 1
                """,
                (resolved_url,),
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
                    source_kind, input_source, local_archive, pdf_path, content_hash, fetch_status, fetch_error,
                    fetched_at, metadata_json, llm_status, llm_error, llm_generated_at, llm_model,
                    tags_json, scores_json, structured_summary_json, embedding_status, embedding_error,
                    embedded_at, embedding_model, embedding_dimensions, embedding_text_hash, related_notes_json,
                    favorite, purpose, date_reviewed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    record.input_source,
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
                    record.favorite,
                    record.purpose,
                    record.date_reviewed,
                ),
            )

    def update_note(self, record: NoteRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE notes
                SET source_url = ?, resolved_url = ?, note_path = ?, date_saved = ?, status = ?,
                    title = ?, summary = ?, source_kind = ?, input_source = ?, local_archive = ?, pdf_path = ?,
                    content_hash = ?, fetch_status = ?, fetch_error = ?, fetched_at = ?,
                    metadata_json = ?, llm_status = ?, llm_error = ?, llm_generated_at = ?,
                    llm_model = ?, tags_json = ?, scores_json = ?, structured_summary_json = ?,
                    embedding_status = ?, embedding_error = ?, embedded_at = ?, embedding_model = ?,
                    embedding_dimensions = ?, embedding_text_hash = ?, related_notes_json = ?,
                    favorite = ?, purpose = ?, date_reviewed = ?
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
                    record.input_source,
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
                    record.favorite,
                    record.purpose,
                    record.date_reviewed,
                    record.note_id,
                ),
            )

    def set_favorite(self, note_id: str, value: bool) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE notes SET favorite = ? WHERE note_id = ?", (1 if value else 0, note_id))
            conn.commit()

    def list_favorite_notes(self, limit: int = 200) -> list[NoteRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {_NOTE_COLUMNS} FROM notes WHERE favorite = 1 ORDER BY date_saved DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

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
            conn.execute("DELETE FROM proposals")
        return int(note_count), int(idea_count)

    def list_notes_for_reindexing(self) -> list[NoteRecord]:
        with self.connect() as conn:
            rows = conn.execute(f"""
                SELECT {_NOTE_COLUMNS}
                FROM notes
                ORDER BY date_saved ASC
                """).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_recent_notes(self, limit: int, offset: int = 0, status: str | None = None) -> list[NoteRecord]:
        clause, params = _status_clause(status)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {_NOTE_COLUMNS} FROM notes WHERE {clause} ORDER BY date_saved DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
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

    def list_notes_with_tag(self, tag: str) -> list[NoteRecord]:
        # LIKE prefilters cheaply; the exact membership check guards against
        # substring false positives (e.g. "graph" vs "graphs").
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {_NOTE_COLUMNS} FROM notes WHERE tags_json IS NOT NULL AND tags_json LIKE ?",
                (f'%"{tag}"%',),
            ).fetchall()
        result: list[NoteRecord] = []
        for row in rows:
            try:
                tags = json.loads(row["tags_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(tags, list) and tag in tags:
                result.append(_row_to_record(row))
        return result

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
                    SUM(CASE WHEN embedding_status = 'skipped' THEN 1 ELSE 0 END) as embedding_skipped,
                    SUM(CASE WHEN status = 'unreviewed' THEN 1 ELSE 0 END) as unreviewed,
                    SUM(CASE WHEN status = 'reviewed' THEN 1 ELSE 0 END) as reviewed,
                    SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) as archived,
                    SUM(CASE WHEN status = 'unreviewed' AND (purpose IS NULL OR purpose != 'Keep')
                        THEN 1 ELSE 0 END) as inbox
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
            unreviewed=row["unreviewed"] or 0,
            reviewed=row["reviewed"] or 0,
            archived=row["archived"] or 0,
            inbox=row["inbox"] or 0,
        )

    def list_notes_by_tag(self, tag: str, limit: int, offset: int = 0, status: str | None = None) -> list[NoteRecord]:
        clause, params = _status_clause(status)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE llm_status = 'generated' AND {clause} AND tags_json LIKE ?
                    ORDER BY date_saved DESC LIMIT ? OFFSET ?""",
                (*params, f'%"{tag}"%', limit, offset),
            ).fetchall()
        records = [_row_to_record(row) for row in rows]
        return [r for r in records if tag in _parse_tags_json(r.tags_json)]

    def list_inbox_notes(
        self, limit: int, offset: int = 0, sort: str = "newest", purpose: str | None = None
    ) -> list[NoteRecord]:
        """The review queue: unreviewed notes that actually warrant reading.

        Excludes archived notes and ``purpose='Keep'`` (knowledge kept on purpose but not
        meant to be read). ``sort`` is one of newest/oldest (by date) or relevance/by_purpose
        (computed in Python from the JSON columns, since the corpus is small). ``purpose``
        optionally narrows to a single class ("Unsorted" => no purpose set).
        """
        base = "WHERE status = 'unreviewed' AND (purpose IS NULL OR purpose != 'Keep')"
        params: list[str] = []
        if purpose == "Unsorted":
            base += " AND purpose IS NULL"
        elif purpose:
            base += " AND purpose = ?"
            params.append(purpose)
        if sort in ("relevance", "by_purpose"):
            # Pull the eligible set, then order in Python over the parsed JSON / nullable fields.
            with self.connect() as conn:
                rows = conn.execute(f"SELECT {_NOTE_COLUMNS} FROM notes {base}", params).fetchall()
            records = [_row_to_record(row) for row in rows]
            if sort == "relevance":
                records.sort(key=lambda r: (_overall_score(r), r.date_saved), reverse=True)
            else:  # by_purpose: group by purpose name, Unsorted last, newest within a group
                records.sort(key=lambda r: (r.purpose or "~", r.date_saved == ""), reverse=False)
                records.sort(key=lambda r: r.date_saved, reverse=True)
                records.sort(key=lambda r: (r.purpose or "~"))
            return records[offset:offset + limit]
        order = "ASC" if sort == "oldest" else "DESC"
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {_NOTE_COLUMNS} FROM notes {base} ORDER BY date_saved {order} LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_notes_on_day(self, month_day: str, limit: int = 20) -> list[NoteRecord]:
        """Notes saved on this calendar day (MM-DD) in any year — "On This Day"."""
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE substr(date_saved, 6, 5) = ? AND status != 'archived'
                    ORDER BY date_saved DESC LIMIT ?""",
                (month_day, limit),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_stale_unreviewed(self, before_iso: str, limit: int = 200) -> list[NoteRecord]:
        """Unreviewed, read-worthy (not Keep) notes older than a cutoff — Forgotten Gems source."""
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE status = 'unreviewed' AND (purpose IS NULL OR purpose != 'Keep')
                      AND date_saved < ?
                    ORDER BY date_saved ASC LIMIT ?""",
                (before_iso, limit),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_notes_by_purpose(self, purpose: str, limit: int, offset: int = 0, status: str | None = None) -> list[NoteRecord]:
        clause, params = _status_clause(status)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE purpose = ? AND {clause}
                    ORDER BY date_saved DESC LIMIT ? OFFSET ?""",
                (purpose, *params, limit, offset),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_notes_by_input_source(self, input_source: str, limit: int, offset: int = 0, status: str | None = None) -> list[NoteRecord]:
        clause, params = _status_clause(status)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT {_NOTE_COLUMNS} FROM notes
                    WHERE input_source = ? AND {clause}
                    ORDER BY date_saved DESC LIMIT ? OFFSET ?""",
                (input_source, *params, limit, offset),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

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

    def insert_proposal(self, record: ProposalRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO proposals ({_PROPOSAL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.proposal_id,
                    record.created_at,
                    record.kind,
                    record.status,
                    record.note_ids_json,
                    record.payload_json,
                    record.resolved_at,
                ),
            )

    def find_by_proposal_id(self, proposal_id: str) -> ProposalRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT {_PROPOSAL_COLUMNS} FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return _row_to_proposal(row) if row else None

    def list_proposals(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[ProposalRecord]:
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    f"""SELECT {_PROPOSAL_COLUMNS} FROM proposals WHERE status = ?
                        ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""SELECT {_PROPOSAL_COLUMNS} FROM proposals
                        ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (limit, offset),
                ).fetchall()
        return [_row_to_proposal(row) for row in rows]

    def update_proposal_status(self, proposal_id: str, status: str, resolved_at: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE proposals SET status = ?, resolved_at = ? WHERE proposal_id = ?",
                (status, resolved_at, proposal_id),
            )

    def count_proposals(self, status: str | None = None) -> int:
        with self.connect() as conn:
            if status:
                row = conn.execute("SELECT COUNT(*) FROM proposals WHERE status = ?", (status,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()
        return int(row[0] or 0)

    def pending_proposal_exists(self, kind: str, note_ids_json: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM proposals WHERE kind = ? AND note_ids_json = ? AND status = 'pending'",
                (kind, note_ids_json),
            ).fetchone()
        return row is not None

    def delete_proposal(self, proposal_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM proposals WHERE proposal_id = ?", (proposal_id,))
        return cursor.rowcount > 0

    def proposal_id_exists(self, proposal_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            _add_missing_proposal_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_usage (
                    day TEXT PRIMARY KEY,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    calls INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def add_token_usage(self, prompt_tokens: int, completion_tokens: int, total_tokens: int, day: str | None = None) -> None:
        """Accumulate one call's token usage into the per-day running totals."""
        day = day or datetime.now(UTC).date().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO token_usage (day, prompt_tokens, completion_tokens, total_tokens, calls)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(day) DO UPDATE SET
                    prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                    completion_tokens = completion_tokens + excluded.completion_tokens,
                    total_tokens = total_tokens + excluded.total_tokens,
                    calls = calls + 1
                """,
                (day, prompt_tokens, completion_tokens, total_tokens),
            )
            conn.commit()

    def get_token_usage(self) -> "TokenUsage":
        """Return cumulative and today's running token totals."""
        today = datetime.now(UTC).date().isoformat()
        with self.connect() as conn:
            total = conn.execute(
                "SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(completion_tokens),0) c, "
                "COALESCE(SUM(total_tokens),0) t, COALESCE(SUM(calls),0) n FROM token_usage"
            ).fetchone()
            day = conn.execute(
                "SELECT prompt_tokens p, completion_tokens c, total_tokens t, calls n FROM token_usage WHERE day = ?",
                (today,),
            ).fetchone()
        return TokenUsage(
            total_tokens=total["t"] or 0,
            prompt_tokens=total["p"] or 0,
            completion_tokens=total["c"] or 0,
            calls=total["n"] or 0,
            today_total_tokens=(day["t"] if day else 0) or 0,
            today_calls=(day["n"] if day else 0) or 0,
        )


_NOTE_COLUMNS = """
    note_id, source_url, resolved_url, note_path, date_saved, status, title, summary,
    source_kind, input_source, local_archive, pdf_path, content_hash, fetch_status, fetch_error, fetched_at, metadata_json,
    llm_status, llm_error, llm_generated_at, llm_model, tags_json, scores_json, structured_summary_json,
    embedding_status, embedding_error, embedded_at, embedding_model, embedding_dimensions,
    embedding_text_hash, related_notes_json, favorite, purpose, date_reviewed
"""

_ADDED_COLUMNS = {
    "source_kind": "TEXT NOT NULL DEFAULT 'unknown'",
    "input_source": "TEXT NOT NULL DEFAULT 'unknown'",
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
    "favorite": "INTEGER NOT NULL DEFAULT 0",
    "purpose": "TEXT",
    "date_reviewed": "TEXT",
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
            # Migrate the old "job_relevant" flag into the renamed "favorite" column.
            if column == "favorite" and "job_relevant" in existing:
                conn.execute("UPDATE notes SET favorite = job_relevant")


def _add_missing_idea_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
    for column, definition in _IDEA_ADDED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE ideas ADD COLUMN {column} {definition}")


_PROPOSAL_COLUMNS = "proposal_id, created_at, kind, status, note_ids_json, payload_json, resolved_at"

_PROPOSAL_ADDED_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'pending'",
    "note_ids_json": "TEXT",
    "payload_json": "TEXT",
    "resolved_at": "TEXT",
}


def _add_missing_proposal_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(proposals)")}
    for column, definition in _PROPOSAL_ADDED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {column} {definition}")


def _row_to_proposal(row: sqlite3.Row) -> ProposalRecord:
    return ProposalRecord(
        proposal_id=row["proposal_id"],
        created_at=row["created_at"],
        kind=row["kind"],
        status=row["status"],
        note_ids_json=row["note_ids_json"],
        payload_json=row["payload_json"],
        resolved_at=row["resolved_at"],
    )


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
        input_source=row["input_source"],
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
        favorite=row["favorite"] if "favorite" in row.keys() else 0,
        purpose=row["purpose"] if "purpose" in row.keys() else None,
        date_reviewed=row["date_reviewed"] if "date_reviewed" in row.keys() else None,
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


def _status_clause(status: str | None) -> tuple[str, list[str]]:
    """SQL fragment + params for filtering note lists by review status.

    None  -> active view (hide archived); "all" -> no filter; else exact match.
    """
    if status is None:
        return "status != 'archived'", []
    if status == "all":
        return "1=1", []
    return "status = ?", [status]


def _parse_tags_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _overall_score(record: NoteRecord) -> float:
    """The note's overall score (0 when unscored / unparseable), for ranking."""
    if not record.scores_json:
        return 0.0
    try:
        data = json.loads(record.scores_json)
        value = data.get("overall") if isinstance(data, dict) else None
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def _keyword_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in query.lower().replace("_", " ").split():
        term = "".join(ch for ch in raw if ch.isalnum() or ch == "-").strip("-")
        if len(term) >= 3 and term not in terms:
            terms.append(term)
    return terms[:8]

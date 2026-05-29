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
            row = conn.execute(
                """
                SELECT note_id, source_url, resolved_url, note_path, date_saved, status, title, summary
                FROM notes
                WHERE source_url = ?
                """,
                (source_url,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def find_by_note_id(self, note_id: str) -> NoteRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT note_id, source_url, resolved_url, note_path, date_saved, status, title, summary
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
                    note_id, source_url, resolved_url, note_path, date_saved, status, title, summary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
    )

from __future__ import annotations

import asyncio
import json
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from prism.db import NoteRecord, PrismDatabase
from prism.embedding import EmbeddingConfig, EmbeddingResult
from prism.index import IndexResult, NoteIndexer, RelatedCandidate, canonical_index_text, rebuild_index
from prism.notes import normalize_related_notes, render_note


def note(**overrides) -> NoteRecord:
    data = {
        "note_id": "abc123",
        "source_url": "https://example.com/a",
        "resolved_url": "https://example.com/a",
        "note_path": "notes/a.md",
        "date_saved": "2026-01-01T00:00:00Z",
        "status": "unreviewed",
        "title": "Robotics Note",
        "summary": "A note about robot manipulation.",
        "source_kind": "website",
        "fetch_status": "fetched",
        "tags_json": json.dumps(["robotics", "vla"]),
    }
    data.update(overrides)
    return NoteRecord(**data)


class Phase4DatabaseTests(unittest.TestCase):
    def test_migrates_phase3_schema_with_embedding_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "prism.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE notes (
                    note_id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE, resolved_url TEXT NOT NULL,
                    note_path TEXT NOT NULL, date_saved TEXT NOT NULL, status TEXT NOT NULL,
                    title TEXT NOT NULL, summary TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT 'unknown',
                    local_archive TEXT, pdf_path TEXT, content_hash TEXT,
                    fetch_status TEXT NOT NULL DEFAULT 'not_fetched', fetch_error TEXT, fetched_at TEXT, metadata_json TEXT,
                    llm_status TEXT NOT NULL DEFAULT 'skipped', llm_error TEXT, llm_generated_at TEXT, llm_model TEXT,
                    tags_json TEXT, scores_json TEXT, structured_summary_json TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO notes (note_id, source_url, resolved_url, note_path, date_saved, status, title, summary)
                VALUES ('abc123', 'https://example.com', 'https://example.com', 'notes/a.md',
                        '2026-01-01T00:00:00Z', 'unreviewed', 'Old', 'Summary')
                """
            )
            conn.commit()
            conn.close()

            db = PrismDatabase(db_path)
            record = db.find_by_note_id("abc123")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.embedding_status, "skipped")
            self.assertIsNone(record.related_notes_json)

    def test_updates_embedding_metadata_without_rewriting_note_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PrismDatabase(Path(tmp) / "prism.sqlite3")
            db.insert_note(note())
            db.update_embedding_metadata(
                "abc123",
                embedding_status="indexed",
                embedded_at="2026-01-01T00:00:01Z",
                embedding_model="embed-a",
                embedding_dimensions=3,
                embedding_text_hash="hash",
            )

            stored = db.find_by_note_id("abc123")
            assert stored is not None
            self.assertEqual(stored.title, "Robotics Note")
            self.assertEqual(stored.embedding_status, "indexed")
            self.assertEqual(stored.embedding_dimensions, 3)


class Phase4IndexTests(unittest.TestCase):
    def test_missing_embedding_config_skips_indexing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PrismDatabase(Path(tmp) / "prism.sqlite3")
            db.insert_note(note())
            indexer = NoteIndexer(Path(tmp) / "lancedb", EmbeddingConfig())

            result = indexer.index_record(note(), db)

            self.assertEqual(result.status, "skipped")
            self.assertEqual(db.find_by_note_id("abc123").embedding_status, "skipped")

    def test_mocked_embedding_success_writes_metadata_and_upserts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PrismDatabase(Path(tmp) / "prism.sqlite3")
            record = note()
            db.insert_note(record)
            indexer = NoteIndexer(Path(tmp) / "lancedb", EmbeddingConfig(api_key="key", model="embed-a"))
            indexer.embedding_client.embed = Mock(return_value=EmbeddingResult([0.1, 0.2, 0.3], "embed-a"))
            indexer._upsert = Mock()

            result = indexer.index_record(record, db)

            self.assertEqual(result.status, "indexed")
            indexer._upsert.assert_called_once()
            stored = db.find_by_note_id("abc123")
            assert stored is not None
            self.assertEqual(stored.embedding_model, "embed-a")
            self.assertEqual(stored.embedding_dimensions, 3)
            self.assertIsNotNone(stored.embedding_text_hash)

    def test_embedding_failure_records_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PrismDatabase(Path(tmp) / "prism.sqlite3")
            record = note()
            db.insert_note(record)
            indexer = NoteIndexer(Path(tmp) / "lancedb", EmbeddingConfig(api_key="key", model="embed-a"))
            indexer.embedding_client.embed = Mock(side_effect=RuntimeError("boom"))

            result = indexer.index_record(record, db)

            self.assertEqual(result.status, "failed")
            stored = db.find_by_note_id("abc123")
            assert stored is not None
            self.assertEqual(stored.embedding_status, "failed")
            self.assertIn("boom", stored.embedding_error or "")

    def test_canonical_index_text_is_stable_and_non_empty(self) -> None:
        record = note(structured_summary_json=json.dumps({"quick_summary": "Quick", "detailed_summary": "Detailed"}))
        self.assertEqual(canonical_index_text(record), canonical_index_text(record))
        self.assertIn("Robotics Note", canonical_index_text(record))
        self.assertIn("Detailed", canonical_index_text(record))

    def test_rebuild_index_reports_counts(self) -> None:
        fake_db = Mock()
        fake_db.list_notes_for_reindexing.return_value = [note(note_id="a"), note(note_id="b"), note(note_id="c")]
        fake_indexer = Mock()
        fake_indexer.index_record.side_effect = [
            IndexResult("indexed"),
            IndexResult("skipped"),
            IndexResult("failed", "bad"),
        ]
        with patch("prism.index.load_index_settings_from_env", return_value=(Path("db"), fake_db, fake_indexer)):
            self.assertEqual(rebuild_index(), (1, 1, 1))


class Phase4RelatedRenderTests(unittest.TestCase):
    def test_related_note_normalization_tolerates_malformed_values(self) -> None:
        candidates = [RelatedCandidate("def456", "Related Title", "Summary", "notes/related-title.md", "https://b", ["robotics"], 0.9)]
        related = normalize_related_notes(["bad", {"id": "def456", "reason": "Same robot stack"}, {"id": "def456"}], candidates)
        self.assertEqual(related, [{"id": "def456", "title": "Related Title", "reason": "Same robot stack", "path": "notes/related-title.md", "origin": "llm"}])
        self.assertEqual(normalize_related_notes({"id": "bad"}, candidates), [])

    def test_generated_note_renders_related_frontmatter_and_obsidian_links(self) -> None:
        record = note(
            llm_status="generated",
            related_notes_json=json.dumps([{"id": "def456", "title": "Related Title", "reason": "Same robot stack", "path": "notes/related-title.md"}]),
            structured_summary_json=json.dumps({"quick_summary": "Quick", "detailed_summary": "Detailed"}),
        )
        rendered = render_note(record, "Extracted")
        self.assertIn("related_notes:\n- def456", rendered)
        self.assertIn("## Related Notes", rendered)
        self.assertIn("[[related-title|Related Title]] - Same robot stack", rendered)


TELEGRAM_AVAILABLE = importlib.util.find_spec("telegram") is not None
if TELEGRAM_AVAILABLE:
    from prism.bot import PrismBot


@unittest.skipUnless(TELEGRAM_AVAILABLE, "python-telegram-bot is not installed")
class Phase4BotRelatedTests(unittest.TestCase):
    def test_related_requires_argument(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        update = _update()
        context = _context([])

        asyncio.run(bot.handle_related(update, context))

        self.assertEqual(update.effective_message.replies[-1], "Usage: /related <query-or-note_id> [n]")

    def test_related_reports_missing_embedding_config(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.notes = Mock(indexer=Mock(is_configured=False))
        update = _update()

        asyncio.run(bot.handle_related(update, _context(["robotics"])))

        self.assertIn("Semantic search is not configured", update.effective_message.replies[-1])

    def test_related_text_query_returns_results(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = None
        indexer = Mock(is_configured=True)
        indexer.search_text.return_value = [RelatedCandidate("abc123", "A", "Summary text", "notes/a.md", "https://a", [], 0.75)]
        bot.notes = Mock(indexer=indexer)
        update = _update()

        asyncio.run(bot.handle_related(update, _context(["robotics"])))

        self.assertIn("<b>A</b> (0.750)", update.effective_message.replies[-1])
        self.assertIn("/more abc123", update.effective_message.replies[-1])

    def test_related_note_id_query_uses_record_text(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = note()
        indexer = Mock(is_configured=True)
        indexer.search_related.return_value = []
        indexer.index_is_empty.return_value = True
        bot.notes = Mock(indexer=indexer)
        update = _update()

        asyncio.run(bot.handle_related(update, _context(["abc123"])))

        indexer.search_related.assert_called_once()
        self.assertIn("semantic index is empty", update.effective_message.replies[-1])


class _Message:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


def _update():
    return Mock(effective_message=_Message())


def _context(args):
    return Mock(args=args)


if __name__ == "__main__":
    unittest.main()

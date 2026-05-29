from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from prism.db import IdeaRecord, NoteRecord, NoteStats, PrismDatabase
from prism.index import RelatedCandidate
from prism.notes import DeleteResult, NoteService, RetryFailedResult, SaveResult, ReprocessResult, WipeResult


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
        "llm_status": "generated",
        "tags_json": json.dumps(["robotics", "vla"]),
    }
    data.update(overrides)
    return NoteRecord(**data)


class Phase5DatabaseTests(unittest.TestCase):
    def _db(self, tmp: str) -> PrismDatabase:
        return PrismDatabase(Path(tmp) / "prism.sqlite3")

    def test_list_recent_notes_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            self.assertEqual(db.list_recent_notes(5), [])

    def test_list_recent_notes_descending_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", date_saved="2026-01-01T00:00:00Z"))
            db.insert_note(note(note_id="bbb222", source_url="https://b.com", date_saved="2026-03-01T00:00:00Z"))
            db.insert_note(note(note_id="ccc333", source_url="https://c.com", date_saved="2026-02-01T00:00:00Z"))
            records = db.list_recent_notes(3)
            self.assertEqual([r.note_id for r in records], ["bbb222", "ccc333", "aaa111"])

    def test_list_recent_notes_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", date_saved="2026-01-01T00:00:00Z"))
            db.insert_note(note(note_id="bbb222", source_url="https://b.com", date_saved="2026-03-01T00:00:00Z"))
            db.insert_note(note(note_id="ccc333", source_url="https://c.com", date_saved="2026-02-01T00:00:00Z"))
            records = db.list_recent_notes(2)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].note_id, "bbb222")

    def test_list_tags_with_counts_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            self.assertEqual(db.list_tags_with_counts(), [])

    def test_list_tags_with_counts_aggregates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", tags_json=json.dumps(["robotics", "vla"])))
            db.insert_note(note(note_id="bbb222", source_url="https://b.com", tags_json=json.dumps(["robotics", "vla"])))
            db.insert_note(note(note_id="ccc333", source_url="https://c.com", tags_json=json.dumps(["robotics"])))
            result = db.list_tags_with_counts()
            self.assertEqual(result[0], ("robotics", 3))
            self.assertEqual(result[1], ("vla", 2))

    def test_list_tags_excludes_non_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", llm_status="skipped", tags_json=json.dumps(["robotics"])))
            self.assertEqual(db.list_tags_with_counts(), [])

    def test_list_notes_by_tag_returns_matching_most_recent_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", date_saved="2026-01-01T00:00:00Z", tags_json=json.dumps(["robotics"])))
            db.insert_note(note(note_id="bbb222", source_url="https://b.com", date_saved="2026-03-01T00:00:00Z", tags_json=json.dumps(["robotics"])))
            db.insert_note(note(note_id="ccc333", source_url="https://c.com", date_saved="2026-02-01T00:00:00Z", tags_json=json.dumps(["vla"])))
            records = db.list_notes_by_tag("robotics", 10)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].note_id, "bbb222")
            self.assertEqual(records[1].note_id, "aaa111")

    def test_list_notes_by_tag_no_prefix_false_positive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", tags_json=json.dumps(["robotics-arm"])))
            records = db.list_notes_by_tag("robotics", 10)
            self.assertEqual(records, [])

    def test_list_notes_by_tag_excludes_non_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", llm_status="skipped", tags_json=json.dumps(["robotics"])))
            self.assertEqual(db.list_notes_by_tag("robotics", 10), [])

    def test_get_note_stats_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            stats = db.get_note_stats()
            self.assertEqual(stats.total, 0)
            self.assertEqual(stats.llm_generated, 0)
            self.assertEqual(stats.embedding_indexed, 0)

    def test_get_note_stats_counts_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", llm_status="generated", embedding_status="indexed"))
            db.insert_note(note(note_id="bbb222", source_url="https://b.com", llm_status="failed", embedding_status="failed"))
            db.insert_note(note(note_id="ccc333", source_url="https://c.com", llm_status="skipped", embedding_status="skipped"))
            stats = db.get_note_stats()
            self.assertEqual(stats.total, 3)
            self.assertEqual(stats.llm_generated, 1)
            self.assertEqual(stats.llm_failed, 1)
            self.assertEqual(stats.llm_skipped, 1)
            self.assertEqual(stats.embedding_indexed, 1)
            self.assertEqual(stats.embedding_failed, 1)
            self.assertEqual(stats.embedding_skipped, 1)


    def test_search_notes_keyword_matches_structured_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", title="Vision Policy", structured_summary_json=json.dumps({"detailed_summary": "VLA manipulation stack"})))
            db.insert_note(note(note_id="bbb222", source_url="https://b.com", title="Other", tags_json=json.dumps(["planning"])))

            records = db.search_notes_keyword("VLA manipulation", 5)

            self.assertEqual([r.note_id for r in records], ["aaa111"])

    def test_list_failed_notes_returns_failed_llm_or_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note(note_id="aaa111", source_url="https://a.com", llm_status="failed"))
            db.insert_note(note(note_id="bbb222", source_url="https://b.com", embedding_status="failed"))
            db.insert_note(note(note_id="ccc333", source_url="https://c.com"))

            records = db.list_failed_notes(10)

            self.assertEqual([r.note_id for r in records], ["aaa111", "bbb222"])

    def test_delete_note_removes_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note())

            self.assertTrue(db.delete_note("abc123"))
            self.assertIsNone(db.find_by_note_id("abc123"))
            self.assertFalse(db.delete_note("abc123"))

    def test_delete_all_removes_notes_and_ideas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_note(note())
            db.insert_idea(IdeaRecord(
                idea_id="idea01",
                created_at="2026-01-01T00:00:00Z",
                title="Idea",
                summary="Summary",
            ))

            counts = db.delete_all()

            self.assertEqual(counts, (1, 1))
            self.assertEqual(db.list_recent_notes(5), [])
            self.assertEqual(db.list_recent_ideas(5), [])


class Phase5MaintenanceServiceTests(unittest.TestCase):
    def test_delete_note_removes_file_archive_index_and_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            vault = root / "vault"
            archive = root / "archives"
            note_file = vault / "notes" / "a.md"
            archive_dir = archive / "abc123"
            note_file.parent.mkdir(parents=True)
            archive_dir.mkdir(parents=True)
            note_file.write_text("note", encoding="utf-8")
            (archive_dir / "extracted.txt").write_text("text", encoding="utf-8")
            db.insert_note(note(local_archive=str(archive_dir)))
            indexer = Mock()
            service = NoteService(vault, db, archive, indexer=indexer)

            result = service.delete_note("abc123")

            self.assertTrue(result.ok)
            self.assertFalse(note_file.exists())
            self.assertFalse(archive_dir.exists())
            self.assertIsNone(db.find_by_note_id("abc123"))
            indexer.delete_record.assert_called_once_with("abc123")

    def test_wipe_all_keeps_profile_but_clears_saved_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            vault = root / "vault"
            archive = root / "archives"
            db.insert_note(note())
            db.insert_idea(IdeaRecord(
                idea_id="idea01",
                created_at="2026-01-01T00:00:00Z",
                title="Idea",
                summary="Summary",
            ))
            (vault / "notes").mkdir(parents=True)
            (vault / "notes" / "a.md").write_text("note", encoding="utf-8")
            (vault / "generated-ideas").mkdir(parents=True)
            (vault / "generated-ideas" / "idea.md").write_text("idea", encoding="utf-8")
            (archive / "abc123").mkdir(parents=True)
            indexer = Mock(lancedb_path=root / "lancedb")
            indexer.lancedb_path.mkdir()
            (indexer.lancedb_path / "cache").write_text("x", encoding="utf-8")
            service = NoteService(vault, db, archive, indexer=indexer)

            result = service.wipe_all()

            self.assertEqual((result.notes, result.ideas), (1, 1))
            self.assertTrue((vault / "profile" / "personal.md").exists())
            self.assertEqual(list((vault / "notes").iterdir()), [])
            self.assertEqual(list((vault / "generated-ideas").iterdir()), [])
            self.assertEqual(list(archive.iterdir()), [])
            self.assertEqual(list(indexer.lancedb_path.iterdir()), [])
            self.assertEqual(db.list_recent_notes(5), [])
            self.assertEqual(db.list_recent_ideas(5), [])

    def test_reset_profile_writes_llm_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives")
            service.llm_config = Mock(is_configured=True)

            with patch("prism.notes.LLMClient") as MockClient:
                MockClient.return_value.rewrite_profile.return_value = "# Personal Profile\n\nUpdated."
                result = service.reset_profile("I like robotics.")

            self.assertTrue(result.ok)
            self.assertIn("Updated", service.profile_path.read_text(encoding="utf-8"))
            MockClient.return_value.rewrite_profile.assert_called_once()
            self.assertEqual(MockClient.return_value.rewrite_profile.call_args.kwargs["mode"], "reset")

    def test_update_profile_passes_current_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives")
            service.llm_config = Mock(is_configured=True)
            service.profile_path.write_text("# Personal Profile\n\nOld.", encoding="utf-8")

            with patch("prism.notes.LLMClient") as MockClient:
                MockClient.return_value.rewrite_profile.return_value = "# Personal Profile\n\nOld and new."
                result = service.update_profile("Add new fact.")

            self.assertTrue(result.ok)
            kwargs = MockClient.return_value.rewrite_profile.call_args.kwargs
            self.assertEqual(kwargs["mode"], "update")
            self.assertIn("Old", kwargs["current_profile"])



TELEGRAM_AVAILABLE = importlib.util.find_spec("telegram") is not None
if TELEGRAM_AVAILABLE:
    from prism.bot import PAGE_SIZE, PrismBot


class _Message:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.markups: list[object] = []
        self.parse_modes: list[str | None] = []

    async def reply_text(self, text: str, reply_markup=None, **kwargs) -> None:
        self.replies.append(text)
        self.markups.append(reply_markup)
        self.parse_modes.append(kwargs.get("parse_mode"))


def _update():
    return Mock(effective_message=_Message())


def _context(args):
    return Mock(args=args)


@unittest.skipUnless(TELEGRAM_AVAILABLE, "python-telegram-bot is not installed")
class Phase5BotTests(unittest.TestCase):
    def test_handle_help_lists_commands(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        update = _update()

        asyncio.run(bot.handle_help(update, _context([])))

        reply = update.effective_message.replies[-1]
        self.assertIn("/ask", reply)
        self.assertIn("/idea", reply)
        self.assertIn("/help", reply)

    def test_handle_start_includes_help(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        update = _update()

        asyncio.run(bot.handle_start(update, _context([])))

        reply = update.effective_message.replies[-1]
        self.assertIn("Send a URL", reply)
        self.assertIn("/ask", reply)

    def test_handle_message_known_url_replies_immediately(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_source_url.return_value = note()
        update = _update()
        update.effective_message.text = "https://example.com/a"

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_message(update, _context([])))
            mock_task.assert_not_called()

        self.assertTrue(update.effective_message.replies[-1].startswith("<b>Already saved:</b>"))

    def test_handle_message_new_url_acks_and_spawns_task(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_source_url.return_value = None
        update = _update()
        update.effective_message.text = "https://example.com/new"

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_message(update, _context([])))
            mock_task.assert_called_once()

        self.assertEqual(update.effective_message.replies[-1], "Saving...")

    def test_handle_more_without_id_uses_latest_note(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_recent_notes.return_value = [note(title="Latest <Note>", summary="Latest & summary.")]
        update = _update()

        asyncio.run(bot.handle_more(update, _context([])))

        reply = update.effective_message.replies[-1]
        self.assertIn("<b>Latest &lt;Note&gt;</b>", reply)
        self.assertIn("Latest &amp; summary.", reply)
        self.assertEqual(update.effective_message.parse_modes[-1], "HTML")
        bot.database.list_recent_notes.assert_called_once_with(1)

    def test_handle_more_without_id_reports_empty_vault(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_recent_notes.return_value = []
        update = _update()

        asyncio.run(bot.handle_more(update, _context([])))

        self.assertEqual(update.effective_message.replies[-1], "No notes saved yet.")

    def test_handle_reprocess_unknown_id_replies_immediately(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = None
        update = _update()

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_reprocess(update, _context(["missing"])))
            mock_task.assert_not_called()

        self.assertEqual(update.effective_message.replies[-1], "No note found for missing.")

    def test_handle_reprocess_valid_acks_and_spawns_task(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = note()
        update = _update()

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_reprocess(update, _context(["abc123"])))
            mock_task.assert_called_once()

        self.assertEqual(update.effective_message.replies[-1], "Reprocessing abc123...")

    def test_recent_first_page_queries_with_offset(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_recent_notes.return_value = [note()]
        update = _update()

        asyncio.run(bot.handle_recent(update, _context([])))

        bot.database.list_recent_notes.assert_called_once_with(PAGE_SIZE + 1, 0)
        self.assertIsNone(update.effective_message.markups[-1])  # one page, no nav

    def test_recent_next_button_when_more(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_recent_notes.return_value = [note(note_id=f"id{i}") for i in range(PAGE_SIZE + 1)]
        update = _update()

        asyncio.run(bot.handle_recent(update, _context([])))

        markup = update.effective_message.markups[-1]
        labels = [b.text for row in markup.inline_keyboard for b in row]
        self.assertTrue(any("Next" in label for label in labels))
        self.assertFalse(any("Prev" in label for label in labels))

    def test_recent_formats_reply(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_recent_notes.return_value = [note()]
        update = _update()

        asyncio.run(bot.handle_recent(update, _context([])))

        reply = update.effective_message.replies[-1]
        self.assertIn("Robotics Note", reply)
        self.assertIn("/more abc123", reply)
        self.assertIn("Recent notes:", reply)

    def test_tags_no_args_shows_list(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_tags_with_counts.return_value = [("robotics", 5), ("vla", 3)]
        update = _update()

        asyncio.run(bot.handle_tags(update, _context([])))

        reply = update.effective_message.replies[-1]
        self.assertIn("#robotics (5)", reply)
        self.assertIn("#vla (3)", reply)

    def test_tags_with_arg_shows_notes(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_notes_by_tag.return_value = [note()]
        update = _update()

        asyncio.run(bot.handle_tags(update, _context(["robotics"])))

        reply = update.effective_message.replies[-1]
        self.assertIn("Notes tagged #robotics:", reply)
        self.assertIn("/more abc123", reply)

    def test_tags_strips_leading_hash(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_notes_by_tag.return_value = [note()]
        update = _update()

        asyncio.run(bot.handle_tags(update, _context(["#robotics"])))

        bot.database.list_notes_by_tag.assert_called_once_with("robotics", PAGE_SIZE + 1, 0)

    def test_handle_page_next_edits_message(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot.database = Mock()
        bot.database.list_recent_notes.return_value = [note()]
        query = Mock()
        query.data = "pg:recent:5"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = Mock(callback_query=query, effective_user=Mock(id=1))

        asyncio.run(bot.handle_page(update, Mock()))

        bot.database.list_recent_notes.assert_called_once_with(PAGE_SIZE + 1, 5)
        query.edit_message_text.assert_awaited_once()
        markup = query.edit_message_text.call_args.kwargs["reply_markup"]
        labels = [b.text for row in markup.inline_keyboard for b in row]
        self.assertTrue(any("Prev" in label for label in labels))

    def test_handle_page_unauthorized(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot.database = Mock()
        query = Mock()
        query.data = "pg:recent:5"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = Mock(callback_query=query, effective_user=Mock(id=2))

        asyncio.run(bot.handle_page(update, Mock()))

        query.edit_message_text.assert_not_called()
        bot.database.list_recent_notes.assert_not_called()

    def test_find_no_args_shows_usage(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        update = _update()

        asyncio.run(bot.handle_find(update, _context([])))

        self.assertEqual(update.effective_message.replies[-1], "Usage: /find <query>")

    def test_find_unconfigured_reports_not_configured(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.notes = Mock(indexer=Mock(is_configured=False))
        update = _update()

        asyncio.run(bot.handle_find(update, _context(["robotics manipulation"])))

        self.assertIn("not configured", update.effective_message.replies[-1])

    def test_find_valid_query_acks_and_spawns_task(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.notes = Mock(indexer=Mock(is_configured=True))
        update = _update()

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_find(update, _context(["robotics", "manipulation"])))
            mock_task.assert_called_once()

        self.assertIn("Searching", update.effective_message.replies[-1])

    def test_status_shows_counts(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        stats = NoteStats(total=10, llm_generated=8, llm_failed=1, llm_skipped=1,
                          embedding_indexed=7, embedding_failed=2, embedding_skipped=1)
        bot.database = Mock()
        bot.database.get_note_stats.return_value = stats
        bot.notes = Mock(indexer=Mock(is_configured=False))
        update = _update()

        asyncio.run(bot.handle_status(update, _context([])))

        reply = update.effective_message.replies[-1]
        self.assertIn("<b>Notes:</b> 10", reply)
        self.assertIn("8 generated", reply)
        self.assertIn("7 indexed", reply)

    def test_status_shows_index_ready_when_configured_and_non_empty(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.get_note_stats.return_value = NoteStats(0, 0, 0, 0, 0, 0, 0)
        indexer = Mock(is_configured=True)
        indexer.index_is_empty.return_value = False
        bot.notes = Mock(indexer=indexer)
        update = _update()

        asyncio.run(bot.handle_status(update, _context([])))

        self.assertIn("<b>Index:</b> ready", update.effective_message.replies[-1])

    def test_related_accepts_optional_limit(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = None
        indexer = Mock(is_configured=True)
        indexer.search_text.return_value = []
        indexer.index_is_empty.return_value = False
        bot.notes = Mock(indexer=indexer)
        update = _update()

        asyncio.run(bot.handle_related(update, _context(["robotics", "10"])))

        indexer.search_text.assert_called_once_with("robotics", limit=10)

    def test_related_clamps_limit_to_20(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = None
        indexer = Mock(is_configured=True)
        indexer.search_text.return_value = []
        indexer.index_is_empty.return_value = False
        bot.notes = Mock(indexer=indexer)
        update = _update()

        asyncio.run(bot.handle_related(update, _context(["robotics", "99"])))

        indexer.search_text.assert_called_once_with("robotics", limit=20)

    def test_related_default_limit_5(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = None
        indexer = Mock(is_configured=True)
        indexer.search_text.return_value = []
        indexer.index_is_empty.return_value = False
        bot.notes = Mock(indexer=indexer)
        update = _update()

        asyncio.run(bot.handle_related(update, _context(["robotics"])))

        indexer.search_text.assert_called_once_with("robotics", limit=20)

    def test_find_task_paginates_semantic_results(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        bot.notes.indexer.search_text.return_value = [
            RelatedCandidate(f"id{i}", f"Title {i}", "Summary", f"notes/{i}.md", "https://example.com", [], 0.9)
            for i in range(PAGE_SIZE + 1)
        ]
        message = _Message()

        asyncio.run(bot._find_task("robotics", message))

        self.assertIn("Title 0", message.replies[-1])
        self.assertNotIn(f"Title {PAGE_SIZE}", message.replies[-1])
        self.assertIsNotNone(message.markups[-1])

    def test_handle_semantic_page_edits_cached_results(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot._semantic_pages = {
            "tok": (
                "Search results:",
                [
                    RelatedCandidate(f"id{i}", f"Title {i}", "Summary", f"notes/{i}.md", "https://example.com", [], 0.9)
                    for i in range(PAGE_SIZE + 1)
                ],
            )
        }
        query = Mock(data=f"sp:tok:{PAGE_SIZE}")
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = Mock(callback_query=query, effective_user=Mock(id=1))

        asyncio.run(bot.handle_semantic_page(update, Mock()))

        edited = query.edit_message_text.call_args.args[0]
        self.assertIn(f"Title {PAGE_SIZE}", edited)

    def test_handle_retry_failed_acks_and_spawns_task(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        update = _update()

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_retry_failed(update, _context(["10"])))
            mock_task.assert_called_once()

        self.assertEqual(update.effective_message.replies[-1], "Retrying up to 10 failed notes...")

    def test_handle_delete_note_prompts_with_buttons(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.find_by_note_id.return_value = note()
        bot.database.find_by_idea_id.return_value = None
        update = _update()

        asyncio.run(bot.handle_delete(update, _context(["abc123"])))

        self.assertIn("Delete note", update.effective_message.replies[-1])
        markup = update.effective_message.markups[-1]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("delete:note:abc123:yes", callbacks)
        self.assertIn("delete:note:abc123:no", callbacks)

    def test_handle_delete_callback_confirms_note_delete(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot.notes = Mock()
        bot.notes.delete_note.return_value = DeleteResult(ok=True, message="Deleted note abc123: Robotics Note")
        query = Mock(data="delete:note:abc123:yes")
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = Mock(callback_query=query, effective_user=Mock(id=1))

        asyncio.run(bot.handle_delete_callback(update, Mock()))

        bot.notes.delete_note.assert_called_once_with("abc123")
        query.edit_message_text.assert_awaited_once()
        self.assertIn("Deleted note", query.edit_message_text.call_args.args[0])

    def test_handle_delete_callback_cancel(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot.notes = Mock()
        query = Mock(data="delete:note:abc123:no")
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = Mock(callback_query=query, effective_user=Mock(id=1))

        asyncio.run(bot.handle_delete_callback(update, Mock()))

        bot.notes.delete_note.assert_not_called()
        query.edit_message_text.assert_awaited_once_with("Delete cancelled.")

    def test_handle_wipe_all_requires_random_code(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot._wipe_codes = {}
        update = _update()
        update.effective_user = Mock(id=1)

        with patch("prism.bot.secrets.token_hex", return_value="a1b2c3"):
            asyncio.run(bot.handle_wipe_all(update, _context([])))

        self.assertEqual(bot._wipe_codes[1], "A1B2C3")
        self.assertIn("/wipe_all A1B2C3", update.effective_message.replies[-1])

    def test_handle_wipe_all_with_matching_code_wipes(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot._wipe_codes = {1: "ABC123"}
        bot.notes = Mock()
        bot.notes.wipe_all.return_value = WipeResult(notes=2, ideas=1)
        update = _update()
        update.effective_user = Mock(id=1)

        asyncio.run(bot.handle_wipe_all(update, _context(["abc123"])))

        bot.notes.wipe_all.assert_called_once()
        self.assertEqual(update.effective_message.replies[-1], "Wiped 2 notes and 1 ideas.")

    def test_handle_reset_me_acks_and_spawns_task(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        update = _update()

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_reset_me(update, _context(["I", "like", "robots"])))
            mock_task.assert_called_once()

        self.assertEqual(update.effective_message.replies[-1], "Resetting personal profile...")

    def test_handle_update_me_no_args_shows_usage(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        update = _update()

        asyncio.run(bot.handle_update_me(update, _context([])))

        self.assertIn("Usage: /update_me", update.effective_message.replies[-1])



@unittest.skipUnless(TELEGRAM_AVAILABLE, "python-telegram-bot is not installed")
class Phase5BackgroundTaskTests(unittest.TestCase):
    def test_save_url_task_success(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        saved = note(llm_status="generated", summary="Great summary.")
        result = SaveResult(record=saved, created=True)

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._save_url_task("https://example.com", message))

        self.assertTrue(message.replies[-1].startswith("<b>Saved:</b>"))

    def test_save_url_task_content_hash_dup(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        result = SaveResult(record=note(), created=False, duplicate_reason="content_hash")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._save_url_task("https://example.com", message))

        self.assertTrue(message.replies[-1].startswith("<b>Already saved:</b>"))

    def test_save_url_task_source_url_dup(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        result = SaveResult(record=note(), created=False, duplicate_reason="source_url")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._save_url_task("https://example.com", message))

        self.assertTrue(message.replies[-1].startswith("<b>Already saved:</b>"))

    def test_save_url_task_exception(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("timeout"))):
            asyncio.run(bot._save_url_task("https://example.com", message))

        self.assertIn("Failed to save", message.replies[-1])
        self.assertIn("timeout", message.replies[-1])

    def test_reprocess_task_success(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        saved = note(llm_status="generated", summary="Great summary.")
        result = ReprocessResult(record=saved, ok=True, message="ok")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._reprocess_task("abc123", message))

        self.assertTrue(message.replies[-1].startswith("<b>Reprocessed:</b>"))

    def test_reprocess_task_failure(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        result = ReprocessResult(record=note(), ok=False, message="LLM failed: bad json")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._reprocess_task("abc123", message))

        self.assertEqual(message.replies[-1], "LLM failed: bad json")

    def test_reprocess_task_not_found(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        result = ReprocessResult(record=None, ok=False, message="No note found for xyz.")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._reprocess_task("xyz", message))

        self.assertEqual(message.replies[-1], "No note found for xyz.")

    def test_reprocess_task_exception(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("db error"))):
            asyncio.run(bot._reprocess_task("abc123", message))

        self.assertIn("Reprocess failed", message.replies[-1])

    def test_retry_failed_task_reports_summary(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        result = RetryFailedResult(total=2, retried=2, repaired=1, failed=1, skipped=0, messages=["abc123: bad json"])

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._retry_failed_task(25, message))

        self.assertIn("Retry complete", message.replies[-1])
        self.assertIn("repaired 1", message.replies[-1])

    def test_profile_task_success_shows_preview(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        bot.notes.update_profile.return_value = Mock(ok=True, message="Profile update complete.", profile="# Personal Profile\n\nNew.")
        message = _Message()

        asyncio.run(bot._profile_task("update", "new", message))

        self.assertIn("Profile update complete", message.replies[-1])
        self.assertIn("Personal Profile", message.replies[-1])



if __name__ == "__main__":
    unittest.main()

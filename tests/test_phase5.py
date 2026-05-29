from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from prism.db import NoteRecord, NoteStats, PrismDatabase
from prism.index import RelatedCandidate
from prism.notes import SaveResult, ReprocessResult


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


if __name__ == "__main__":
    unittest.main()

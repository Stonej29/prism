from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from prism.db import IdeaRecord, NoteRecord, PrismDatabase
from prism.ideas import IdeaResult, IdeaService, render_idea
from prism.llm import LLMConfig, LLMGeneration, build_idea_context


def idea_record(**overrides) -> IdeaRecord:
    data = {
        "idea_id": "abc123",
        "created_at": "2026-01-01T00:00:00Z",
        "title": "Robot Idea",
        "summary": "A buildable robotics idea.",
        "topic": "robotics",
        "note_path": "generated-ideas/2026-01-01-robot-idea.md",
        "llm_status": "generated",
        "llm_model": "model-a",
        "structured_json": json.dumps(idea_structured()),
        "tags_json": json.dumps(["robotics", "vla"]),
        "source_note_ids_json": json.dumps(["src001"]),
    }
    data.update(overrides)
    return IdeaRecord(**data)


def idea_structured() -> dict[str, object]:
    return {
        "title": "Robot Idea",
        "summary": "A buildable robotics idea.",
        "problem": "Manipulation is hard.",
        "approach": "Use a small VLA controller.",
        "why_it_fits": "Matches the robotics interests.",
        "components": ["camera", "policy network"],
        "risks": ["needs real-world validation"],
        "related_notes": [
            {"id": "src001", "title": "Source Note", "reason": "Shared method", "path": "notes/2026-01-01-source.md"}
        ],
        "tags": ["robotics", "vla"],
    }


def note(**overrides) -> NoteRecord:
    data = {
        "note_id": "src001",
        "source_url": "https://example.com/a",
        "resolved_url": "https://example.com/a",
        "note_path": "notes/2026-01-01-source.md",
        "date_saved": "2026-01-01T00:00:00Z",
        "status": "unreviewed",
        "title": "Source Note",
        "summary": "A note about robot manipulation.",
        "source_kind": "website",
        "fetch_status": "fetched",
        "llm_status": "generated",
        "tags_json": json.dumps(["robotics"]),
    }
    data.update(overrides)
    return NoteRecord(**data)


class Phase6DatabaseTests(unittest.TestCase):
    def _db(self, tmp: str) -> PrismDatabase:
        return PrismDatabase(Path(tmp) / "prism.sqlite3")

    def test_insert_and_find_idea(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_idea(idea_record())
            found = db.find_by_idea_id("abc123")
            self.assertIsNotNone(found)
            self.assertEqual(found.title, "Robot Idea")
            self.assertIsNone(found.rating)

    def test_find_unknown_idea_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            self.assertIsNone(db.find_by_idea_id("missing"))

    def test_update_idea_rating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_idea(idea_record())
            db.update_idea_rating("abc123", 4, "2026-02-01T00:00:00Z")
            found = db.find_by_idea_id("abc123")
            self.assertEqual(found.rating, 4)
            self.assertEqual(found.rated_at, "2026-02-01T00:00:00Z")

    def test_list_recent_ideas_descending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_idea(idea_record(idea_id="aaa111", created_at="2026-01-01T00:00:00Z"))
            db.insert_idea(idea_record(idea_id="bbb222", created_at="2026-03-01T00:00:00Z"))
            db.insert_idea(idea_record(idea_id="ccc333", created_at="2026-02-01T00:00:00Z"))
            records = db.list_recent_ideas(3)
            self.assertEqual([r.idea_id for r in records], ["bbb222", "ccc333", "aaa111"])

    def test_list_rated_ideas_orders_by_rating_and_excludes_unrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            db.insert_idea(idea_record(idea_id="aaa111"))
            db.insert_idea(idea_record(idea_id="bbb222"))
            db.insert_idea(idea_record(idea_id="ccc333"))
            db.update_idea_rating("aaa111", 3, "2026-02-01T00:00:00Z")
            db.update_idea_rating("bbb222", 5, "2026-02-02T00:00:00Z")
            records = db.list_rated_ideas(10)
            self.assertEqual([r.idea_id for r in records], ["bbb222", "aaa111"])

    def test_idea_id_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            self.assertFalse(db.idea_id_exists("abc123"))
            db.insert_idea(idea_record())
            self.assertTrue(db.idea_id_exists("abc123"))

    def test_schema_migration_adds_idea_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            conn = sqlite3.connect(path)
            conn.execute(
                "CREATE TABLE ideas (idea_id TEXT PRIMARY KEY, created_at TEXT, title TEXT, summary TEXT)"
            )
            conn.commit()
            conn.close()

            db = PrismDatabase(path)
            db.insert_idea(idea_record())
            found = db.find_by_idea_id("abc123")
            self.assertEqual(found.llm_status, "generated")
            self.assertIsNone(found.rating)


class Phase6LLMTests(unittest.TestCase):
    def test_build_idea_context_shape(self) -> None:
        ctx = build_idea_context(
            topic="robotics",
            knowledge=[{"id": "a", "title": "T"}],
            past_ideas=[{"title": "x", "summary": "s", "rating": 5}],
        )
        self.assertEqual(ctx["topic"], "robotics")
        self.assertEqual(ctx["knowledge"], [{"id": "a", "title": "T"}])
        self.assertEqual(ctx["past_rated_ideas"][0]["rating"], 5)

    def test_generate_idea_retries_without_response_format_on_400(self) -> None:
        import json as json_module

        calls: list[dict[str, object]] = []

        class FakeClient:
            def __init__(self, timeout) -> None:
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def post(self, url, headers, json):
                calls.append(json)
                if len(calls) == 1:
                    response = httpx.Response(400, request=httpx.Request("POST", url))
                    raise httpx.HTTPStatusError("bad", request=response.request, response=response)
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"model": "model-a", "choices": [{"message": {"content": json_module.dumps(idea_structured())}}]},
                )

        from prism.llm import LLMClient

        with patch("prism.llm.httpx.Client", FakeClient):
            generation = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).generate_idea(
                {"topic": "robotics"}, "profile"
            )

        self.assertEqual(len(calls), 2)
        self.assertIn("response_format", calls[0])
        self.assertNotIn("response_format", calls[1])
        self.assertEqual(generation.data["title"], "Robot Idea")


class Phase6IdeaServiceTests(unittest.TestCase):
    def _service(self, tmp: str, configured: bool = True) -> tuple[IdeaService, PrismDatabase]:
        db = PrismDatabase(Path(tmp) / "prism.sqlite3")
        api_key = "key" if configured else None
        model = "model-a" if configured else None
        service = IdeaService(Path(tmp) / "vault", db, LLMConfig("https://llm.example", api_key, model), None)
        return service, db

    def test_generate_idea_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self._service(tmp, configured=False)
            result = service.generate_idea("robotics")
            self.assertFalse(result.ok)
            self.assertIn("LLM", result.message)

    def test_generate_idea_success_writes_file_and_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, db = self._service(tmp)
            db.insert_note(note())
            generation = LLMGeneration(data=idea_structured(), model="model-a")
            with patch("prism.ideas.LLMClient") as MockClient:
                MockClient.return_value.generate_idea.return_value = generation
                result = service.generate_idea("robotics")

            self.assertTrue(result.ok)
            self.assertIsNotNone(result.record)
            stored = db.find_by_idea_id(result.record.idea_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.llm_status, "generated")
            note_file = service.vault_path / result.record.note_path
            self.assertTrue(note_file.exists())
            self.assertIn("type: idea", note_file.read_text(encoding="utf-8"))

    def test_generate_idea_llm_failure_persists_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, db = self._service(tmp)
            with patch("prism.ideas.LLMClient") as MockClient:
                MockClient.return_value.generate_idea.side_effect = RuntimeError("boom")
                result = service.generate_idea("robotics")

            self.assertFalse(result.ok)
            stored = db.find_by_idea_id(result.record.idea_id)
            self.assertEqual(stored.llm_status, "failed")
            self.assertTrue((service.vault_path / result.record.note_path).exists())

    def test_record_rating_updates_db_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, db = self._service(tmp)
            generation = LLMGeneration(data=idea_structured(), model="model-a")
            with patch("prism.ideas.LLMClient") as MockClient:
                MockClient.return_value.generate_idea.return_value = generation
                result = service.generate_idea("robotics")

            updated = service.record_rating(result.record.idea_id, 4)
            self.assertEqual(updated.rating, 4)
            self.assertEqual(db.find_by_idea_id(result.record.idea_id).rating, 4)
            content = (service.vault_path / updated.note_path).read_text(encoding="utf-8")
            self.assertIn("rating: 4", content)

    def test_record_rating_unknown_idea(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self._service(tmp)
            self.assertIsNone(service.record_rating("missing", 3))


class Phase6RenderTests(unittest.TestCase):
    def test_render_idea_sections_links_and_rating(self) -> None:
        md = render_idea(idea_record(rating=4))
        self.assertIn("type: idea", md)
        self.assertIn("rating: 4", md)
        self.assertIn("## Problem", md)
        self.assertIn("## Approach", md)
        self.assertIn("## Components", md)
        self.assertIn("[[2026-01-01-source|Source Note]]", md)

    def test_render_idea_fallback_when_failed(self) -> None:
        md = render_idea(idea_record(llm_status="failed", llm_error="boom", structured_json=None))
        self.assertIn("LLM status: failed", md)
        self.assertIn("boom", md)


TELEGRAM_AVAILABLE = importlib.util.find_spec("telegram") is not None
if TELEGRAM_AVAILABLE:
    from telegram import InlineKeyboardMarkup

    from prism.bot import PrismBot


class _Message:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.markups: list[object] = []

    async def reply_text(self, text: str, reply_markup=None, **kwargs) -> None:
        self.replies.append(text)
        self.markups.append(reply_markup)


def _update():
    return Mock(effective_message=_Message())


def _context(args):
    return Mock(args=args)


def _callback_update(data: str, user_id: int = 1):
    query = Mock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = Mock(callback_query=query, effective_user=Mock(id=user_id))
    return update, query


@unittest.skipUnless(TELEGRAM_AVAILABLE, "python-telegram-bot is not installed")
class Phase6BotTests(unittest.TestCase):
    def test_handle_idea_not_configured(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.ideas = Mock(llm_config=Mock(is_configured=False))
        update = _update()

        asyncio.run(bot.handle_idea(update, _context([])))

        self.assertIn("LLM", update.effective_message.replies[-1])

    def test_handle_idea_valid_acks_and_spawns_task(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.ideas = Mock(llm_config=Mock(is_configured=True))
        update = _update()

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_idea(update, _context(["robotics"])))
            mock_task.assert_called_once()

        self.assertIn("Generating idea", update.effective_message.replies[-1])

    def test_idea_task_success_includes_rating_buttons(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.ideas = Mock()
        message = _Message()
        result = IdeaResult(record=idea_record(), ok=True, message="A buildable robotics idea.")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._idea_task("robotics", message))

        self.assertTrue(message.replies[-1].startswith("<b>Idea:</b>"))
        markup = message.markups[-1]
        self.assertIsInstance(markup, InlineKeyboardMarkup)
        self.assertEqual(len(markup.inline_keyboard[0]), 5)
        self.assertEqual(markup.inline_keyboard[0][3].callback_data, "idearate:abc123:4")

    def test_idea_task_failure_replies_message_without_markup(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.ideas = Mock()
        message = _Message()
        result = IdeaResult(record=idea_record(), ok=False, message="Idea generation failed: boom")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._idea_task("robotics", message))

        self.assertEqual(message.replies[-1], "Idea generation failed: boom")
        self.assertIsNone(message.markups[-1])

    def test_handle_rating_updates_and_edits_message(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot.ideas = Mock()
        update, query = _callback_update("idearate:abc123:4", user_id=1)

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=idea_record(rating=4))):
            asyncio.run(bot.handle_rating(update, Mock()))

        query.answer.assert_awaited_once()
        query.edit_message_text.assert_awaited_once()
        self.assertIn("★★★★", query.edit_message_text.call_args.args[0])

    def test_handle_rating_unauthorized_does_not_edit(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot.ideas = Mock()
        update, query = _callback_update("idearate:abc123:4", user_id=2)

        asyncio.run(bot.handle_rating(update, Mock()))

        query.answer.assert_awaited_once()
        query.edit_message_text.assert_not_called()

    def test_handle_rating_idea_not_found(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.settings = Mock(telegram_allowed_user_ids={1})
        bot.ideas = Mock()
        update, query = _callback_update("idearate:abc123:4", user_id=1)

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=None)):
            asyncio.run(bot.handle_rating(update, Mock()))

        query.edit_message_text.assert_awaited_once_with("Idea not found.")

    def test_handle_ideas_lists_with_ratings(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_recent_ideas.return_value = [idea_record(rating=5)]
        update = _update()

        asyncio.run(bot.handle_ideas(update, _context([])))

        reply = update.effective_message.replies[-1]
        self.assertIn("Recent ideas:", reply)
        self.assertIn("Robot Idea", reply)
        self.assertIn("★★★★★", reply)

    def test_handle_ideas_empty(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.database = Mock()
        bot.database.list_recent_ideas.return_value = []
        update = _update()

        asyncio.run(bot.handle_ideas(update, _context([])))

        self.assertIn("No ideas yet", update.effective_message.replies[-1])


if __name__ == "__main__":
    unittest.main()

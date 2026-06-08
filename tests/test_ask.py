from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from prism.db import NoteRecord, PrismDatabase
from prism.index import RelatedCandidate
from prism.llm import LLMClient, LLMConfig, build_ask_context
from prism.notes import AskResult, NoteService


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
        "tags_json": json.dumps(["robotics"]),
        "structured_summary_json": json.dumps(
            {"quick_summary": "Quick.", "detailed_summary": "Detailed body.", "key_claims": ["Claim one"]}
        ),
    }
    data.update(overrides)
    return NoteRecord(**data)


def candidate(note_id: str = "abc123", title: str = "Robotics Note", score: float = 0.9) -> RelatedCandidate:
    return RelatedCandidate(
        note_id=note_id,
        title=title,
        summary="A note about robot manipulation.",
        note_path="notes/a.md",
        source_url="https://example.com/a",
        tags=["robotics"],
        score=score,
    )


class AskLLMTests(unittest.TestCase):
    def test_build_ask_context_shape(self) -> None:
        ctx = build_ask_context(question="q", notes=[{"id": "a"}])
        self.assertEqual(ctx, {"question": "q", "notes": [{"id": "a"}]})

    def test_answer_question_returns_assistant_content(self) -> None:
        class FakeClient:
            def __init__(self, timeout) -> None:
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def post(self, url, headers, json):
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"choices": [{"message": {"content": "Grounded answer [abc123]"}}]},
                )

        with patch("prism.llm.httpx.Client", FakeClient):
            answer = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).answer_question(
                {"question": "q", "notes": []}
            )
        self.assertEqual(answer, "Grounded answer [abc123]")


class AskServiceTests(unittest.TestCase):
    def _service(self, tmp: str, indexer, llm_configured: bool = True):
        db = PrismDatabase(Path(tmp) / "prism.sqlite3")
        api_key = "key" if llm_configured else None
        model = "model-a" if llm_configured else None
        service = NoteService(
            Path(tmp) / "vault",
            db,
            Path(tmp) / "archives",
            LLMConfig("https://llm.example", api_key, model),
            indexer,
        )
        return service, db

    def test_ask_success_uses_structured_summary_and_returns_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            indexer = Mock(is_configured=True)
            indexer.search_text.return_value = [candidate()]
            service, db = self._service(tmp, indexer)
            db.insert_note(note())

            with patch("prism.notes.LLMClient") as MockClient:
                MockClient.return_value.answer_question.return_value = "Answer text [abc123]"
                result = service.ask("what about robotics?")

            self.assertTrue(result.ok)
            self.assertEqual(result.answer, "Answer text [abc123]")
            self.assertEqual(result.sources[0].note_id, "abc123")
            ctx = MockClient.return_value.answer_question.call_args.args[0]
            self.assertEqual(ctx["question"], "what about robotics?")
            self.assertEqual(ctx["notes"][0]["detailed_summary"], "Detailed body.")
            self.assertEqual(ctx["notes"][0]["key_claims"], ["Claim one"])

    def test_ask_merges_keyword_matches_after_semantic_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            indexer = Mock(is_configured=True)
            indexer.search_text.return_value = [candidate("abc123", "Semantic Note", 0.9)]
            service, db = self._service(tmp, indexer)
            db.insert_note(note(note_id="abc123", source_url="https://example.com/a", title="Semantic Note"))
            db.insert_note(note(note_id="def456", source_url="https://example.com/b", title="Keyword Note", summary="Mentions tactile manipulation."))

            with patch("prism.notes.LLMClient") as MockClient:
                MockClient.return_value.answer_question.return_value = "Answer text [abc123] [def456]"
                result = service.ask("tactile manipulation")

            self.assertTrue(result.ok)
            self.assertEqual([source.note_id for source in result.sources], ["abc123", "def456"])
            ctx = MockClient.return_value.answer_question.call_args.args[0]
            self.assertEqual([item["id"] for item in ctx["notes"]], ["abc123", "def456"])

    def test_ask_no_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            indexer = Mock(is_configured=True)
            indexer.search_text.return_value = []
            indexer.index_is_empty.return_value = False
            service, _ = self._service(tmp, indexer)
            result = service.ask("anything")
            self.assertFalse(result.ok)
            self.assertIn("nothing saved", result.message)

    def test_ask_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            indexer = Mock(is_configured=True)
            indexer.search_text.return_value = []
            indexer.index_is_empty.return_value = True
            service, _ = self._service(tmp, indexer)
            result = service.ask("anything")
            self.assertFalse(result.ok)
            self.assertIn("index is empty", result.message)

    def test_ask_embedding_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self._service(tmp, None)
            result = service.ask("anything")
            self.assertFalse(result.ok)
            self.assertIn("Semantic search is not configured", result.message)

    def test_ask_llm_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            indexer = Mock(is_configured=True)
            service, _ = self._service(tmp, indexer, llm_configured=False)
            result = service.ask("anything")
            self.assertFalse(result.ok)
            self.assertIn("LLM_API_KEY", result.message)

    def test_ask_llm_failure_returns_not_ok_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            indexer = Mock(is_configured=True)
            indexer.search_text.return_value = [candidate()]
            service, db = self._service(tmp, indexer)
            db.insert_note(note())

            with patch("prism.notes.LLMClient") as MockClient:
                MockClient.return_value.answer_question.side_effect = RuntimeError("boom")
                result = service.ask("what about robotics?")

            self.assertFalse(result.ok)
            self.assertIn("Answer failed", result.message)
            self.assertEqual(result.sources[0].note_id, "abc123")


TELEGRAM_AVAILABLE = importlib.util.find_spec("telegram") is not None
if TELEGRAM_AVAILABLE:
    from prism.bot import PrismBot


class _Message:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, reply_markup=None, **kwargs) -> None:
        self.replies.append(text)


def _update():
    return Mock(effective_message=_Message())


def _context(args):
    return Mock(args=args)


@unittest.skipUnless(TELEGRAM_AVAILABLE, "python-telegram-bot is not installed")
class AskBotTests(unittest.TestCase):
    def test_handle_ask_no_args_shows_usage(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.notes = Mock(indexer=Mock(is_configured=True), llm_config=Mock(is_configured=True))
        update = _update()

        asyncio.run(bot.handle_ask(update, _context([])))

        self.assertEqual(update.effective_message.replies[-1], "Usage: /ask <question>")

    def test_handle_ask_embedding_not_configured(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.notes = Mock(indexer=Mock(is_configured=False), llm_config=Mock(is_configured=True))
        update = _update()

        asyncio.run(bot.handle_ask(update, _context(["robotics?"])))

        self.assertIn("not configured", update.effective_message.replies[-1])

    def test_handle_ask_llm_not_configured(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.notes = Mock(indexer=Mock(is_configured=True), llm_config=Mock(is_configured=False))
        update = _update()

        asyncio.run(bot.handle_ask(update, _context(["robotics?"])))

        self.assertEqual(update.effective_message.replies[-1], "/ask needs LLM_API_KEY and LLM_MODEL.")

    def test_handle_ask_valid_acks_and_spawns_task(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot._is_allowed = AsyncMock(return_value=True)
        bot.notes = Mock(indexer=Mock(is_configured=True), llm_config=Mock(is_configured=True))
        update = _update()

        with patch("prism.bot.asyncio.create_task") as mock_task:
            asyncio.run(bot.handle_ask(update, _context(["what", "about", "robotics?"])))
            mock_task.assert_called_once()

        self.assertIn("Searching your notes", update.effective_message.replies[-1])

    def test_ask_task_success_reply_has_answer_and_sources(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        result = AskResult(answer="The answer is 42.", sources=[candidate()], ok=True, message="")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._ask_task("q", message))

        reply = message.replies[-1]
        self.assertIn("The answer is 42.", reply)
        self.assertIn("Sources:", reply)
        self.assertIn("/more abc123", reply)

    def test_ask_task_not_ok_replies_message(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()
        result = AskResult(answer="", sources=[], ok=False, message="I have nothing saved about that.")

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(return_value=result)):
            asyncio.run(bot._ask_task("q", message))

        self.assertEqual(message.replies[-1], "I have nothing saved about that.")

    def test_ask_task_exception(self) -> None:
        bot = PrismBot.__new__(PrismBot)
        bot.notes = Mock()
        message = _Message()

        with patch("prism.bot.asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("timeout"))):
            asyncio.run(bot._ask_task("q", message))

        self.assertIn("Ask failed", message.replies[-1])


if __name__ == "__main__":
    unittest.main()

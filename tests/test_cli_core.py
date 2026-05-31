from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from prism.cli_core import CliCore
from prism.config import Settings
from prism.db import IdeaRecord, NoteRecord


def make_note(note_id: str, *, tags=("graph",), title=None) -> NoteRecord:
    return NoteRecord(
        note_id=note_id,
        source_url=f"https://example.com/{note_id}",
        resolved_url=f"https://example.com/{note_id}",
        note_path=f"notes/{note_id}.md",
        date_saved=f"2026-05-2{len(note_id)}T00:00:00Z",
        status="unreviewed",
        title=title or f"Note {note_id}",
        summary=f"Summary for {note_id}",
        source_kind="paper",
        fetch_status="fetched",
        llm_status="generated",
        tags_json=json.dumps(list(tags)),
        scores_json=json.dumps({"relevance": 8, "novelty": 7, "overall": 7}),
        structured_summary_json=json.dumps({"quick_summary": f"Quick {note_id}"}),
        embedding_status="indexed",
    )


def make_idea(idea_id: str, *, rating=None) -> IdeaRecord:
    return IdeaRecord(
        idea_id=idea_id,
        created_at="2026-05-20T00:00:00Z",
        title=f"Idea {idea_id}",
        summary=f"Summary {idea_id}",
        llm_status="generated",
        rating=rating,
    )


def settings_for(root: Path) -> Settings:
    return Settings(
        telegram_bot_token="",
        telegram_allowed_user_ids=frozenset(),
        llm_base_url="https://example.com",
        llm_api_key=None,
        llm_model=None,
        embedding_base_url="https://example.com",
        embedding_api_key=None,
        embedding_model=None,
        vault_path=root / "vault",
        sqlite_path=root / "prism.sqlite3",
        archive_path=root / "archives",
        lancedb_path=root / "lancedb",
    )


class CliCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        # Point feeds at a path that does not exist so ingest() is deterministic.
        os.environ["PRISM_FEEDS_PATH"] = str(root / "feeds.yaml")
        self.core = CliCore.from_settings(settings_for(root))

    def tearDown(self) -> None:
        os.environ.pop("PRISM_FEEDS_PATH", None)
        self._tmp.cleanup()

    def test_capability_gates_unconfigured(self) -> None:
        self.assertFalse(self.core.search_ready())
        self.assertFalse(self.core.llm_ready())

    def test_recent_and_tags_reads(self) -> None:
        self.core.database.insert_note(make_note("aaa111", tags=["graph", "rag"]))
        self.core.database.insert_note(make_note("bbb222", tags=["agents"]))

        recent = self.core.recent_notes(10)
        self.assertEqual({r.note_id for r in recent}, {"aaa111", "bbb222"})

        tags = dict(self.core.tags())
        self.assertEqual(tags["graph"], 1)
        self.assertEqual(tags["agents"], 1)

        graph_notes = self.core.notes_by_tag("graph", 10)
        self.assertEqual([n.note_id for n in graph_notes], ["aaa111"])

    def test_find_and_related_guard_when_unconfigured(self) -> None:
        find = self.core.find("anything")
        self.assertFalse(find.ok)
        self.assertIn("not configured", find.message)

        related = self.core.related("anything")
        self.assertFalse(related.ok)
        self.assertIn("not configured", related.message)

    def test_ask_guard_when_unconfigured(self) -> None:
        result = self.core.ask("what is this")
        self.assertFalse(result.ok)

    def test_status(self) -> None:
        self.core.database.insert_note(make_note("aaa111"))
        info = self.core.status()
        self.assertEqual(info.stats.total, 1)
        self.assertFalse(info.index_configured)
        self.assertEqual(info.pending_proposals, 0)

    def test_rate_idea(self) -> None:
        self.core.database.insert_idea(make_idea("idea01"))
        updated = self.core.rate_idea("idea01", 4)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.rating, 4)
        self.assertIsNone(self.core.rate_idea("missing", 3))

    def test_delete_note(self) -> None:
        self.core.database.insert_note(make_note("aaa111"))
        result = self.core.delete_note("aaa111")
        self.assertTrue(result.ok)
        self.assertIsNone(self.core.note("aaa111"))

    def test_delete_idea(self) -> None:
        self.core.database.insert_idea(make_idea("idea01"))
        removed = self.core.delete_idea("idea01")
        self.assertIsNotNone(removed)
        self.assertIsNone(self.core.idea("idea01"))

    def test_rename_note(self) -> None:
        self.core.database.insert_note(make_note("aaa111", title="Old"))
        result = self.core.rename_note("aaa111", "A Better Title")
        self.assertTrue(result.ok)
        self.assertEqual(result.record.title, "A Better Title")
        self.assertEqual(self.core.note("aaa111").title, "A Better Title")

    def test_rename_note_missing_and_empty(self) -> None:
        self.assertFalse(self.core.rename_note("missing", "x").ok)
        self.core.database.insert_note(make_note("aaa111"))
        empty = self.core.rename_note("aaa111", "   ")
        self.assertFalse(empty.ok)

    def test_set_status(self) -> None:
        self.core.database.insert_note(make_note("aaa111"))
        result = self.core.set_status("aaa111", "reviewed")
        self.assertTrue(result.ok)
        self.assertEqual(self.core.note("aaa111").status, "reviewed")

    def test_set_status_invalid_and_missing(self) -> None:
        self.assertFalse(self.core.set_status("missing", "reviewed").ok)
        self.core.database.insert_note(make_note("aaa111"))
        bad = self.core.set_status("aaa111", "bogus")
        self.assertFalse(bad.ok)
        self.assertIn("Status must be one of", bad.message)

    def test_ingest_without_feeds(self) -> None:
        result = self.core.ingest()
        self.assertFalse(result.ok)
        self.assertIn("No feeds configured", result.message)

    def test_idea_generation_guard(self) -> None:
        result = self.core.generate_idea("robotics")
        self.assertFalse(result.ok)
        self.assertIn("LLM", result.message)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from prism.bot import COMMANDS as BOT_COMMANDS
from prism.cli_core import CliCore
from prism.config import Settings
from prism.db import IdeaRecord, NoteRecord
from prism.tui.app import PrismApp
from prism.tui.commands import COMMAND_NAMES
from prism.tui.messages import ListEntry
from prism.tui.screens.confirm import ConfirmScreen
from prism.tui.screens.main_screen import AtlasScreen
from prism.tui.widgets.command_bar import CommandBar
from prism.tui.widgets.detail import DetailPane
from prism.tui.widgets.sidebar import SourceList


def make_note(note_id: str, *, title=None) -> NoteRecord:
    return NoteRecord(
        note_id=note_id,
        source_url=f"https://example.com/{note_id}",
        resolved_url=f"https://example.com/{note_id}",
        note_path=f"notes/{note_id}.md",
        date_saved="2026-05-20T00:00:00Z",
        status="unreviewed",
        title=title or f"Note {note_id}",
        summary=f"Summary for {note_id}",
        source_kind="paper",
        fetch_status="fetched",
        llm_status="generated",
        tags_json=json.dumps(["graph"]),
        structured_summary_json=json.dumps({"quick_summary": f"Quick {note_id}"}),
    )


def make_idea(idea_id: str) -> IdeaRecord:
    return IdeaRecord(
        idea_id=idea_id,
        created_at="2026-05-20T00:00:00Z",
        title=f"Idea {idea_id}",
        summary=f"Summary {idea_id}",
        llm_status="generated",
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


class _FakeItem:
    def __init__(self, entry: ListEntry) -> None:
        self.entry = entry


class _FakeSelected:
    def __init__(self, entry: ListEntry) -> None:
        self.item = _FakeItem(entry)


class CommandParityTest(unittest.TestCase):
    def test_every_bot_command_is_reachable(self) -> None:
        bot_names = {name for name, _ in BOT_COMMANDS}
        missing = bot_names - COMMAND_NAMES
        self.assertEqual(missing, set(), f"TUI is missing bot commands: {missing}")


class TuiAppTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.environ["PRISM_FEEDS_PATH"] = str(self.root / "feeds.yaml")
        self.core = CliCore.from_settings(settings_for(self.root))

    def tearDown(self) -> None:
        os.environ.pop("PRISM_FEEDS_PATH", None)
        self._tmp.cleanup()

    async def _settle(self, app: PrismApp, pilot) -> None:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_panes_mount(self) -> None:
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, AtlasScreen)
            self.assertIsNotNone(screen.query_one(SourceList))
            self.assertIsNotNone(screen.query_one(DetailPane))
            self.assertIsNotNone(screen.query_one(CommandBar))

    async def test_notes_listed_on_start(self) -> None:
        self.core.database.insert_note(make_note("aaa111"))
        self.core.database.insert_note(make_note("bbb222"))
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            listview = app.screen.query_one(SourceList).list_view
            self.assertEqual(len(listview.children), 2)

    async def test_mode_switch_to_ideas(self) -> None:
        self.core.database.insert_idea(make_idea("idea01"))
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            app.screen.action_set_mode("ideas")
            await self._settle(app, pilot)
            sidebar = app.screen.query_one(SourceList)
            self.assertEqual(sidebar.mode, "ideas")
            self.assertEqual(len(sidebar.list_view.children), 1)

    async def test_selection_renders_detail(self) -> None:
        record = make_note("aaa111", title="Attention Is All You Need")
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            screen = app.screen
            entry = ListEntry(record.note_id, record.title, "note", record)
            screen.on_list_view_selected(_FakeSelected(entry))
            self.assertIn("Attention Is All You Need", screen.query_one(DetailPane).last_markdown)

    async def test_find_unconfigured_falls_back_to_keyword(self) -> None:
        # No embeddings + empty corpus: find no longer errors with "not
        # configured"; it keyword-searches and reports nothing found.
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            app.screen.dispatch_command("find diffusion models")
            await self._settle(app, pilot)
            self.assertIn("No results", app.screen.query_one(CommandBar).last_status)

    async def test_status_set_command(self) -> None:
        self.core.database.insert_note(make_note("aaa111"))
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            app.screen.dispatch_command("status_set aaa111 reviewed")
            await self._settle(app, pilot)
            self.assertEqual(self.core.note("aaa111").status, "reviewed")

    async def test_rename_command(self) -> None:
        self.core.database.insert_note(make_note("aaa111", title="Old"))
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            app.screen.dispatch_command("rename aaa111 A Better Title")
            await self._settle(app, pilot)
            self.assertEqual(self.core.note("aaa111").title, "A Better Title")

    async def test_inbox_command_sets_status_filter(self) -> None:
        self.core.database.insert_note(make_note("aaa111"))
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            app.screen.dispatch_command("inbox")
            await self._settle(app, pilot)
            self.assertEqual(app.screen.note_status, "unreviewed")

    async def test_delete_flow(self) -> None:
        self.core.database.insert_note(make_note("aaa111"))
        app = PrismApp(self.core)
        async with app.run_test() as pilot:
            await self._settle(app, pilot)
            screen = app.screen
            screen.selected = ListEntry("aaa111", "Note aaa111", "note", None)
            screen.action_delete_selected()
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            app.screen.dismiss(True)
            await self._settle(app, pilot)
            self.assertIsNone(self.core.note("aaa111"))


if __name__ == "__main__":
    unittest.main()

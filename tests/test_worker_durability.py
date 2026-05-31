from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from prism.config import Settings
from prism.db import NoteRecord, PrismDatabase
from prism.index import IndexResult, canonical_index_text, hash_text
from prism.worker.backup import run_backup
from prism.worker.config import (
    DEFAULT_BACKUP_CRON,
    DEFAULT_REEMBED_CRON,
    load_worker_config,
    parse_worker_config,
)
from prism.worker.reembed import run_reembed


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
        llm_status="generated",
        tags_json=json.dumps(["graph"]),
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


class _StubServices:
    def __init__(self, settings: Settings, database: PrismDatabase, indexer) -> None:
        self.settings = settings
        self.database = database
        self.indexer = indexer
        self.notes = None
        self.ideas = None


class _StubIndexer:
    """Records which notes get re-indexed; reports them as freshly hashed."""

    def __init__(self, *, configured=True) -> None:
        self.is_configured = configured
        self.reindexed: list[str] = []

    def index_record(self, record: NoteRecord, database=None) -> IndexResult:
        self.reindexed.append(record.note_id)
        text_hash = hash_text(canonical_index_text(record))
        if database is not None:
            database.update_embedding_metadata(record.note_id, embedding_status="indexed", embedding_text_hash=text_hash)
        return IndexResult(status="indexed", text_hash=text_hash)


class ConfigTests(unittest.TestCase):
    def test_parses_backup_and_reembed(self) -> None:
        cfg = parse_worker_config({
            "schedule": {"backup": "0 1 * * *", "reembed": "30 4 * * 2"},
            "backup_enabled": True,
            "reembed_enabled": True,
        })
        self.assertEqual(cfg.backup_cron, "0 1 * * *")
        self.assertEqual(cfg.reembed_cron, "30 4 * * 2")
        self.assertTrue(cfg.backup_enabled)
        self.assertTrue(cfg.reembed_enabled)

    def test_defaults_when_absent(self) -> None:
        cfg = load_worker_config(Path("/nonexistent/feeds.yaml"))
        self.assertEqual(cfg.backup_cron, DEFAULT_BACKUP_CRON)
        self.assertEqual(cfg.reembed_cron, DEFAULT_REEMBED_CRON)
        self.assertFalse(cfg.backup_enabled)
        self.assertFalse(cfg.reembed_enabled)


class ReembedTests(unittest.TestCase):
    def test_reindexes_only_stale_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            indexer = _StubIndexer()
            # fresh: stored hash matches current index text -> skipped
            fresh = make_note("fresh01")
            db.insert_note(replace(fresh, embedding_text_hash=hash_text(canonical_index_text(fresh))))
            # stale: stored hash is wrong -> reindexed
            db.insert_note(replace(make_note("stale1"), embedding_text_hash="deadbeef"))

            summary = run_reembed(_StubServices(settings_for(root), db, indexer))

            self.assertEqual(summary.checked, 2)
            self.assertEqual(summary.stale, 1)
            self.assertEqual(summary.reindexed, 1)
            self.assertEqual(indexer.reindexed, ["stale1"])

    def test_noop_without_indexer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            db.insert_note(make_note("aaa111"))
            summary = run_reembed(_StubServices(settings_for(root), db, _StubIndexer(configured=False)))
            self.assertEqual((summary.checked, summary.reindexed), (0, 0))


class BackupTests(unittest.TestCase):
    def _git(self, *args: str, cwd: Path) -> None:
        subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_commits_vault_and_snapshots_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            db = PrismDatabase(settings.sqlite_path)  # creates the sqlite file
            vault = settings.vault_path
            vault.mkdir(parents=True)
            self._git("init", cwd=vault)
            self._git("config", "user.email", "t@example.com", cwd=vault)
            self._git("config", "user.name", "Test", cwd=vault)
            (vault / "note.md").write_text("hello", encoding="utf-8")

            summary = run_backup(_StubServices(settings, db, None))

            self.assertTrue(summary.vault_committed)
            self.assertIsNotNone(summary.snapshot_path)
            self.assertTrue(Path(summary.snapshot_path).exists())
            self.assertEqual(summary.errors, [])
            log = subprocess.run(["git", "log", "--oneline"], cwd=vault, capture_output=True, text=True)
            self.assertIn("prism backup", log.stdout)

    def test_prunes_old_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            db = PrismDatabase(settings.sqlite_path)
            backups = root / "backups"
            backups.mkdir()
            for i in range(5):
                (backups / f"prism-2026010{i}T000000Z.sqlite3").write_text("x", encoding="utf-8")

            summary = run_backup(_StubServices(settings, db, None), backups_dir=backups, keep=3)

            # 5 old + 1 new = 6, pruned down to keep=3
            remaining = sorted(backups.glob("prism-*.sqlite3"))
            self.assertEqual(len(remaining), 3)
            self.assertGreaterEqual(summary.pruned, 3)

    def test_no_git_repo_records_error_but_still_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            db = PrismDatabase(settings.sqlite_path)
            settings.vault_path.mkdir(parents=True)  # not a git repo

            summary = run_backup(_StubServices(settings, db, None))

            self.assertFalse(summary.vault_committed)
            self.assertTrue(summary.errors)
            self.assertIsNotNone(summary.snapshot_path)


if __name__ == "__main__":
    unittest.main()

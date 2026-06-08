"""Durability pass: commit the vault git repo and snapshot the SQLite DB.

The Markdown vault (`settings.vault_path`) is its own git repo; this commits any
working-tree changes locally (no remote push — we make no assumption about a
configured remote). The SQLite DB is the metadata source of truth, so it is also
copied to a timestamped snapshot under `<sqlite_dir>/backups/`, keeping the most
recent `keep` snapshots.

Every step is best-effort and non-fatal: a missing git repo, a clean tree, or a
copy error is logged and recorded in the summary rather than raised.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from prism.services import Services

LOGGER = logging.getLogger("prism.worker.backup")

DEFAULT_KEEP = 14
_GIT_TIMEOUT = 60


@dataclass
class BackupSummary:
    vault_committed: bool = False
    snapshot_path: str | None = None
    pruned: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def run_backup(services: Services, *, backups_dir: Path | None = None, keep: int = DEFAULT_KEEP) -> BackupSummary:
    summary = BackupSummary()
    settings = services.settings
    vault = Path(settings.vault_path)
    sqlite_path = Path(settings.sqlite_path)
    backups_dir = backups_dir or sqlite_path.parent / "backups"

    summary.vault_committed = _commit_vault(vault, summary)
    _snapshot_sqlite(sqlite_path, backups_dir, keep, summary)

    LOGGER.info(
        "Backup complete: vault_committed=%s snapshot=%s pruned=%d errors=%d",
        summary.vault_committed, summary.snapshot_path, summary.pruned, len(summary.errors),
    )
    return summary


def _commit_vault(vault: Path, summary: BackupSummary) -> bool:
    if not (vault / ".git").exists():
        summary.errors.append(f"vault is not a git repo: {vault}")
        return False
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    try:
        subprocess.run(["git", "add", "-A"], cwd=vault, capture_output=True, timeout=_GIT_TIMEOUT, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=vault, capture_output=True, timeout=_GIT_TIMEOUT, text=True)
        if not status.stdout.strip():
            return False  # nothing to commit
        subprocess.run(
            ["git", "commit", "-m", f"prism backup {stamp}"],
            cwd=vault, capture_output=True, timeout=_GIT_TIMEOUT, check=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        summary.errors.append(f"vault commit failed: {type(exc).__name__}: {exc}")
        return False


def _snapshot_sqlite(sqlite_path: Path, backups_dir: Path, keep: int, summary: BackupSummary) -> None:
    if not sqlite_path.exists():
        summary.errors.append(f"sqlite db not found: {sqlite_path}")
        return
    try:
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = backups_dir / f"prism-{stamp}.sqlite3"
        shutil.copy2(sqlite_path, dest)
        summary.snapshot_path = str(dest)
    except OSError as exc:
        summary.errors.append(f"sqlite snapshot failed: {type(exc).__name__}: {exc}")
        return
    # Prune oldest snapshots beyond `keep`.
    snapshots = sorted(backups_dir.glob("prism-*.sqlite3"))
    for old in snapshots[: max(0, len(snapshots) - keep)]:
        try:
            old.unlink()
            summary.pruned += 1
        except OSError:
            pass

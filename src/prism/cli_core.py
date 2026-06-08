"""UI-agnostic facade shared by the TUI (`prism.tui`) and the CLI (`prism.cli`).

Both front-ends talk to PRISM only through ``CliCore``. It owns the small bits of
orchestration the Telegram bot does inline — wiring a :class:`ProposalService`
alongside the shared :class:`Services`, the ``related`` query/note-id branch, and
loading feeds for ``ingest`` — so that logic lives in exactly one place.

Every method is synchronous and returns plain data or the existing frozen result
dataclasses (``SaveResult``, ``AskResult``, ``IngestionSummary`` …). Nothing here
imports Textual or argparse; the TUI runs the blocking methods on worker threads,
the CLI calls them directly.
"""
from __future__ import annotations

from dataclasses import dataclass

from prism.config import Settings
from prism.db import IdeaRecord, NoteRecord, NoteStats, ProposalRecord
from prism.ideas import IdeaResult
from prism.index import RelatedCandidate
from prism.notes import (
    AskResult,
    DeleteResult,
    ProfileResult,
    RepersonalizeSummary,
    ReprocessAllSummary,
    ReprocessResult,
    RetryFailedResult,
    SaveResult,
    WipeResult,
)
from prism.proposals import ProposalActionResult, ProposalService
from prism.services import Services, build_services
from prism.worker.backup import BackupSummary, run_backup
from prism.worker.config import load_worker_config
from prism.worker.ingest import IngestionSummary, run_feed_ingestion
from prism.worker.reembed import ReembedSummary, run_reembed
from prism.worker.traversal import TraversalSummary, run_graph_traversal

INPUT_SOURCE = "cli"


@dataclass(frozen=True)
class SearchResult:
    """Outcome of ``find``/``related`` — mirrors the bot's guard branches."""

    ok: bool
    message: str
    candidates: list[RelatedCandidate]


@dataclass(frozen=True)
class IngestResult:
    ok: bool
    message: str
    summary: IngestionSummary | None = None


@dataclass(frozen=True)
class EditResult:
    """Outcome of an in-place note edit (rename / set-status)."""

    ok: bool
    message: str
    record: NoteRecord | None = None


@dataclass(frozen=True)
class StatusInfo:
    stats: NoteStats
    index_configured: bool
    index_empty: bool
    pending_proposals: int


class CliCore:
    """Synchronous facade over the PRISM service layer."""

    def __init__(self, services: Services, proposals: ProposalService) -> None:
        self.services = services
        self.proposals = proposals

    @classmethod
    def from_settings(cls, settings: Settings) -> "CliCore":
        services = build_services(settings)
        return cls(services, ProposalService(services.database, services.notes))

    # Convenience accessors -------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self.services.settings

    @property
    def database(self):
        return self.services.database

    @property
    def indexer(self):
        return self.services.indexer

    @property
    def notes(self):
        return self.services.notes

    @property
    def ideas(self):
        return self.services.ideas

    # Capability gates (mirror the bot's guard clauses) ---------------------
    def search_ready(self) -> bool:
        return bool(self.indexer and self.indexer.is_configured)

    def llm_ready(self) -> bool:
        return self.notes.llm_config.is_configured

    # Cheap DB reads --------------------------------------------------------
    def recent_notes(self, limit: int, offset: int = 0, status: str | None = None) -> list[NoteRecord]:
        return self.database.list_recent_notes(limit, offset, status)

    def tags(self) -> list[tuple[str, int]]:
        return self.database.list_tags_with_counts()

    def notes_by_tag(self, tag: str, limit: int, offset: int = 0, status: str | None = None) -> list[NoteRecord]:
        return self.database.list_notes_by_tag(tag, limit, offset, status)

    def recent_ideas(self, limit: int, offset: int = 0) -> list[IdeaRecord]:
        return self.database.list_recent_ideas(limit, offset)

    def pending_proposals(self, limit: int = 50, offset: int = 0) -> list[ProposalRecord]:
        return self.proposals.list_pending(limit, offset)

    def note(self, note_id: str) -> NoteRecord | None:
        return self.database.find_by_note_id(note_id.strip().lower())

    def idea(self, idea_id: str) -> IdeaRecord | None:
        return self.database.find_by_idea_id(idea_id.strip().lower())

    def status(self) -> StatusInfo:
        stats = self.database.get_note_stats()
        configured = self.search_ready()
        empty = self.indexer.index_is_empty() if configured else True
        return StatusInfo(
            stats=stats,
            index_configured=configured,
            index_empty=empty,
            pending_proposals=self.proposals.count_pending(),
        )

    # Blocking / network operations ----------------------------------------
    def save_url(self, url: str, input_source: str = INPUT_SOURCE) -> SaveResult:
        return self.notes.save_url(url, input_source)

    def ask(self, question: str, limit: int = 6) -> AskResult:
        return self.notes.ask(question, limit)

    def find(self, query: str, limit: int = 20) -> SearchResult:
        query = query.strip()
        if not query:
            return SearchResult(ok=False, message="Enter a search query.", candidates=[])
        # Hybrid search: semantic when configured, always blended with keyword,
        # so /find still works (keyword-only) when embeddings are unconfigured.
        results = self.notes.search(query, limit=limit)
        return self._search_outcome(results)

    def related(self, query: str, limit: int = 20) -> SearchResult:
        query = query.strip()
        if not query:
            return SearchResult(ok=False, message="Enter a query or note id.", candidates=[])
        if not self.search_ready():
            return SearchResult(ok=False, message="Semantic search is not configured.", candidates=[])
        try:
            record = self.note(query) if len(query.split()) == 1 else None
            if record:
                results = self.indexer.search_related(record, limit=limit)
            else:
                results = self.indexer.search_text(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            return SearchResult(ok=False, message=f"Related search failed: {type(exc).__name__}: {exc}", candidates=[])
        return self._search_outcome(results)

    def _search_outcome(self, results: list[RelatedCandidate]) -> SearchResult:
        if results:
            return SearchResult(ok=True, message="", candidates=results)
        if self.search_ready() and self.indexer.index_is_empty():
            return SearchResult(
                ok=False,
                message="The semantic index is empty. Run: PYTHONPATH=src python -m prism.index rebuild",
                candidates=[],
            )
        return SearchResult(ok=False, message="No results found.", candidates=[])

    def generate_idea(self, topic: str | None = None) -> IdeaResult:
        return self.ideas.generate_idea(topic)

    def rate_idea(self, idea_id: str, rating: int) -> IdeaRecord | None:
        return self.ideas.record_rating(idea_id.strip().lower(), rating)

    def delete_idea(self, idea_id: str) -> IdeaRecord | None:
        return self.ideas.delete_idea(idea_id)

    def reprocess(self, note_id: str) -> ReprocessResult:
        return self.notes.reprocess(note_id)

    def reprocess_all(self) -> ReprocessAllSummary:
        return self.notes.reprocess_all()

    def repersonalize(self, note_id: str) -> ReprocessResult:
        return self.notes.repersonalize(note_id)

    def repersonalize_all(self) -> RepersonalizeSummary:
        return self.notes.repersonalize_all()

    def retry_failed(self, limit: int = 25) -> RetryFailedResult:
        return self.notes.retry_failed(limit)

    def rename_note(self, note_id: str, title: str) -> EditResult:
        record = self.note(note_id)
        if not record:
            return EditResult(ok=False, message=f"No note found for {note_id}.")
        try:
            updated = self.notes.rename_note(record, title)
        except ValueError as exc:
            return EditResult(ok=False, message=str(exc))
        return EditResult(ok=True, message=f"Renamed {updated.note_id} → {updated.title}", record=updated)

    def set_status(self, note_id: str, status: str) -> EditResult:
        record = self.note(note_id)
        if not record:
            return EditResult(ok=False, message=f"No note found for {note_id}.")
        try:
            updated = self.notes.set_status(record, status)
        except ValueError as exc:
            return EditResult(ok=False, message=str(exc))
        return EditResult(ok=True, message=f"Set {updated.note_id} status to {updated.status}", record=updated)

    def set_status_bulk(self, note_ids: list[str], status: str) -> list[EditResult]:
        return [self.set_status(note_id, status) for note_id in note_ids]

    def delete_note(self, note_id: str) -> DeleteResult:
        return self.notes.delete_note(note_id)

    def wipe_all(self) -> WipeResult:
        return self.notes.wipe_all()

    def reset_profile(self, text: str) -> ProfileResult:
        return self.notes.reset_profile(text)

    def update_profile(self, text: str) -> ProfileResult:
        return self.notes.update_profile(text)

    def approve_proposal(self, proposal_id: str) -> ProposalActionResult:
        return self.proposals.approve(proposal_id)

    def reject_proposal(self, proposal_id: str) -> ProposalActionResult:
        return self.proposals.reject(proposal_id)

    def ingest(self) -> IngestResult:
        config = load_worker_config()
        if not config.feeds:
            return IngestResult(ok=False, message="No feeds configured (set PRISM_FEEDS_PATH / feeds.yaml).")
        summary = run_feed_ingestion(self.notes, config.feeds)
        return IngestResult(ok=True, message="Feed ingestion complete.", summary=summary)

    def traverse(self) -> TraversalSummary:
        return run_graph_traversal(self.services, load_worker_config().traversal)

    def reembed(self) -> ReembedSummary:
        return run_reembed(self.services)

    def backup(self) -> BackupSummary:
        return run_backup(self.services)

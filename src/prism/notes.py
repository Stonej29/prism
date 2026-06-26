from __future__ import annotations

import json
import math
import re
import secrets
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from prism.config import DEFAULT_LLM_BASE_URL
from prism.db import NoteRecord, PrismDatabase
from prism import images as image_extract
from prism.fetch import FetchResult, extract_website_text, fetch_source, fetch_upload
from prism.index import NoteIndexer, RelatedCandidate, canonical_index_text
from prism.llm import LLMClient, LLMConfig, build_ask_context, build_llm_context, build_merge_context

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
PREVIEW_LIMIT = 1500
# Per-note caps for /ask context so large retrieval K cannot blow the context window.
ASK_QUICK_LIMIT = 600
ASK_DETAILED_LIMIT = 1200
ASK_CLAIM_LIMIT = 300
SCORE_FIELDS = ("relevance", "novelty", "credibility", "actionability", "interest", "overall")
# Ground truth vs. personalization split. The personalization pass (call 2) regenerates
# only PERSONAL_PROSE_FIELDS + PERSONAL_SCORE_FIELDS from the note's ground truth + profile;
# everything else (summaries, tags, related_notes, novelty/credibility) is profile-independent
# and is never touched by a re-personalization, so the embedding and graph stay stable.
PERSONAL_PROSE_FIELDS = ("why_it_matters", "personal_relevance", "project_ideas")
PERSONAL_SCORE_FIELDS = ("relevance", "actionability", "interest", "overall")
# Ground-truth fields handed to the personalization pass as read-only context (no source text).
GROUND_TRUTH_CONTEXT_FIELDS = (
    "title", "quick_summary", "detailed_summary", "key_claims",
    "limitations", "technical_details", "tags", "source_kind", "source_url",
)
DEFAULT_PROFILE = """# Personal Profile

Describe the person using PRISM here: their context, goals, interests, and constraints.

Core interests: add topics, domains, tools, and research areas that should influence note relevance and idea generation.

Preferences: describe what makes a note useful, which tradeoffs matter, and what kinds of project ideas should be emphasized.
"""


NOTE_STATUSES = ("unreviewed", "reviewed", "archived")

# Single-select content classification, auto-assigned by the LLM ground-truth pass and
# user-editable. `None` ("Unsorted") means unclassified (LLM unsure or unconfigured).
# `Keep` = worth retaining but not worth reading, so it is excluded from the review queue.
PURPOSE_VALUES = ("Thesis", "Work", "Self-Host", "Dataset", "Keep")


def normalize_purpose(value: str | None) -> str | None:
    """Map a free-form purpose to its canonical casing, or None if unrecognized.

    Matching is case- and separator-insensitive so the LLM (or a user) can pass
    "self host", "self_host", "SELF-HOST" etc. and still land on "Self-Host".
    """
    if not value or not isinstance(value, str):
        return None
    key = re.sub(r"[\s_-]+", "", value).strip().lower()
    for canonical in PURPOSE_VALUES:
        if re.sub(r"[\s_-]+", "", canonical).lower() == key:
            return canonical
    return None


# A near-identical embedding match flags a likely duplicate. Advisory only — it never
# blocks a save (different content hashes with near-identical text are common, e.g. a
# v2 of a paper), it just surfaces "this looks similar to …" so the user can decide.
SEMANTIC_DUP_THRESHOLD = 0.92


@dataclass(frozen=True)
class SaveResult:
    record: NoteRecord
    created: bool
    # Why a save was rejected as a duplicate: "source_url" | "resolved_url" | "content_hash".
    duplicate_reason: str | None = None
    # Advisory near-duplicate hint set when a NEW note was still created (created=True).
    similar_note_id: str | None = None
    similarity: float | None = None


@dataclass(frozen=True)
class ReprocessResult:
    record: NoteRecord | None
    ok: bool
    message: str


@dataclass(frozen=True)
class AskResult:
    answer: str
    sources: list[RelatedCandidate]
    ok: bool
    message: str


@dataclass(frozen=True)
class DeleteResult:
    ok: bool
    message: str
    title: str | None = None


@dataclass(frozen=True)
class RetryFailedResult:
    total: int
    retried: int
    repaired: int
    failed: int
    skipped: int
    messages: list[str]


@dataclass(frozen=True)
class WipeResult:
    notes: int
    ideas: int


@dataclass(frozen=True)
class MergeResult:
    record: NoteRecord | None
    ok: bool
    message: str
    synthesized: bool = False


@dataclass(frozen=True)
class RepersonalizeSummary:
    total: int
    updated: int
    failed: int
    errors: list[str]


@dataclass(frozen=True)
class ReprocessAllSummary:
    total: int
    reprocessed: int
    failed: int
    errors: list[str]


@dataclass(frozen=True)
class ExtractImagesAllSummary:
    total: int
    processed: int
    images: int
    errors: list[str]


@dataclass(frozen=True)
class ProfileResult:
    ok: bool
    message: str
    profile: str | None = None


class NoteService:
    def __init__(
        self,
        vault_path: Path,
        database: PrismDatabase,
        archive_path: Path,
        llm_config: LLMConfig | None = None,
        indexer: NoteIndexer | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.notes_path = vault_path / "notes"
        self.archive_path = archive_path
        self.profile_path = vault_path / "profile" / "personal.md"
        self.database = database
        self.llm_config = llm_config or LLMConfig(DEFAULT_LLM_BASE_URL, None, None)
        self.indexer = indexer
        self.notes_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        ensure_profile(self.profile_path)

    def save_url(self, source_url: str, input_source: str = "telegram", *, force: bool = False) -> SaveResult:
        if not force:
            existing = self.database.find_by_source_url(source_url)
            if existing:
                return SaveResult(record=existing, created=False, duplicate_reason="source_url")

        note_id = self._new_note_id()
        fetch = fetch_source(source_url, self.archive_path, note_id)
        return self._persist_fetch(source_url, fetch, note_id, input_source, force=force)

    def save_upload(
        self,
        filename: str,
        data: bytes,
        content_type: str | None = None,
        input_source: str = "telegram",
        *,
        force: bool = False,
    ) -> SaveResult:
        note_id = self._new_note_id()
        fetch = fetch_upload(data, filename, self.archive_path, note_id, content_type)
        if not force:
            existing = self.database.find_by_source_url(fetch.source_url)
            if existing:
                return SaveResult(record=existing, created=False, duplicate_reason="source_url")
        return self._persist_fetch(fetch.source_url, fetch, note_id, input_source, force=force)

    def _persist_fetch(self, source_url: str, fetch: FetchResult, note_id: str, input_source: str, *, force: bool = False) -> SaveResult:
        saved_at = datetime.now(UTC).replace(microsecond=0)

        if not force:
            # The final URL after redirects may collide with a note saved under a different
            # original URL (e.g. a shortener vs. the canonical link).
            if fetch.resolved_url and fetch.resolved_url != source_url:
                by_resolved = self.database.find_by_resolved_url(fetch.resolved_url)
                if by_resolved:
                    return SaveResult(record=by_resolved, created=False, duplicate_reason="resolved_url")
            duplicate = self.database.find_by_content_hash(fetch.content_hash)
            if duplicate:
                return SaveResult(record=duplicate, created=False, duplicate_reason="content_hash")

        title = clean_title(fetch.title) or placeholder_title(source_url)
        filename = f"{saved_at.date().isoformat()}-{slugify(title)}.md"
        note_path = self._unique_note_path(filename)
        relative_note_path = str(note_path.relative_to(self.vault_path))
        summary = summary_for_fetch(source_url, fetch)

        # Reading-time estimate (~200 wpm), computed here where the extracted text lives.
        words = len(fetch.extracted_text.split())
        metadata = dict(fetch.metadata)
        if words:
            metadata["reading_minutes"] = max(1, round(words / 200))

        record = NoteRecord(
            note_id=note_id,
            source_url=source_url,
            resolved_url=fetch.resolved_url,
            note_path=relative_note_path,
            date_saved=saved_at.isoformat().replace("+00:00", "Z"),
            status="unreviewed",
            title=title,
            summary=summary,
            source_kind=fetch.source_kind,
            input_source=input_source,
            local_archive=fetch.local_archive,
            pdf_path=fetch.pdf_path,
            content_hash=fetch.content_hash,
            fetch_status=fetch.fetch_status,
            fetch_error=fetch.fetch_error,
            fetched_at=fetch.fetched_at,
            metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True),
        )
        # Compute related candidates once and reuse them both for the LLM context and for
        # the advisory near-duplicate hint (avoids a second embedding round-trip).
        related = self._related_candidates(record, fetch.extracted_text)
        similar_note_id, similarity = None, None
        if related and related[0].score >= SEMANTIC_DUP_THRESHOLD:
            similar_note_id, similarity = related[0].note_id, round(related[0].score, 4)
        record = self._apply_llm(record, fetch.extracted_text, metadata, related_candidates=related)
        note_path.write_text(render_note(record, fetch.extracted_text), encoding="utf-8")
        self.database.insert_note(record)
        record = self._index_after_persist(record)
        return SaveResult(record=record, created=True, similar_note_id=similar_note_id, similarity=similarity)

    def _refetch(self, record: NoteRecord) -> NoteRecord:
        """Retry the original fetch in place (browser headers + reader fallback may
        now succeed where the first attempt was blocked), updating fetch fields."""
        fetch = fetch_source(record.source_url, self.archive_path, record.note_id)
        title = record.title
        if (title == placeholder_title(record.source_url) or not title) and clean_title(fetch.title):
            title = clean_title(fetch.title)
        updated = replace(
            record,
            title=title,
            resolved_url=fetch.resolved_url or record.resolved_url,
            source_kind=fetch.source_kind,
            local_archive=fetch.local_archive,
            pdf_path=fetch.pdf_path,
            content_hash=fetch.content_hash or record.content_hash,
            fetch_status=fetch.fetch_status,
            fetch_error=fetch.fetch_error,
            fetched_at=fetch.fetched_at,
            metadata_json=json.dumps(fetch.metadata, ensure_ascii=True, sort_keys=True),
        )
        self.database.update_note(updated)
        return updated

    def reprocess(self, note_id: str) -> ReprocessResult:
        record = self.database.find_by_note_id(note_id.strip().lower())
        if not record:
            return ReprocessResult(record=None, ok=False, message=f"No note found for {note_id}.")
        # If the original capture failed, retry the fetch first instead of refusing.
        if record.fetch_status != "fetched":
            record = self._refetch(record)
            if record.fetch_status != "fetched":
                return ReprocessResult(record=record, ok=False, message=f"Re-fetch failed: {record.fetch_error or 'still blocked'}.")
        if not record.local_archive:
            return ReprocessResult(record=record, ok=False, message=f"Cannot reprocess {record.note_id}: no local archive recorded.")

        extracted_path = Path(record.local_archive) / "extracted.txt"
        if not extracted_path.exists():
            return ReprocessResult(record=record, ok=False, message=f"Cannot reprocess {record.note_id}: archived extracted.txt is missing.")

        extracted_text = extracted_path.read_text(encoding="utf-8")
        metadata = _json_object(record.metadata_json)
        if not extracted_text.strip() and record.local_archive:
            raw_path = Path(record.local_archive) / "raw.html"
            if raw_path.exists():
                _, recovered_text, recovered_metadata = extract_website_text(
                    raw_path.read_text(encoding="utf-8"),
                    record.resolved_url or record.source_url,
                    Path(record.local_archive),
                )
                if recovered_text.strip():
                    extracted_text = recovered_text
                    extracted_path.write_text(extracted_text, encoding="utf-8")
                    metadata = {**metadata, **recovered_metadata}
                    record = replace(record, metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True))
        updated = self._apply_llm(record, extracted_text, metadata, force=True)
        note_path = self.vault_path / updated.note_path
        note_path.write_text(render_note(updated, extracted_text), encoding="utf-8")
        self.database.update_note(updated)
        updated = self._index_after_persist(updated)
        if updated.llm_status == "generated":
            return ReprocessResult(record=updated, ok=True, message=f"Reprocessed: {updated.title}")
        return ReprocessResult(record=updated, ok=False, message=f"LLM {updated.llm_status}: {updated.llm_error or 'not generated'}")

    def reprocess_all(self) -> ReprocessAllSummary:
        """Re-run the full LLM pipeline (ground truth + personalization) + re-embed for every
        fetched note, reusing each note's archived extracted text (no re-fetch / network pull).
        Non-blocking: one note's failure is collected, never aborts the batch. Un-fetched notes
        are skipped since they have no archive to reprocess from."""
        records = [r for r in self.database.list_notes_for_reindexing() if r.fetch_status == "fetched"]
        reprocessed = 0
        errors: list[str] = []
        for record in records:
            try:
                result = self.reprocess(record.note_id)
            except Exception as exc:  # noqa: BLE001 - collect and continue
                errors.append(f"{record.note_id}: {exc}")
                continue
            if result.ok:
                reprocessed += 1
            else:
                errors.append(f"{record.note_id}: {result.message}")
        return ReprocessAllSummary(total=len(records), reprocessed=reprocessed, failed=len(errors), errors=errors)

    def extract_images(self, note_id: str) -> ReprocessResult:
        """Extract (or refresh) source images for one note from its existing archive.

        Reads the already-archived source (source.pdf / raw.html / readme.md / YouTube id) —
        no re-fetch — downscales images into <archive>/images/, and stores the list in the
        note's metadata. Images aren't part of the embedded text or markdown body, so no
        re-embed / re-render is needed."""
        record = self.database.find_by_note_id(note_id.strip().lower())
        if not record:
            return ReprocessResult(record=None, ok=False, message=f"No note found for {note_id}.")
        if not record.local_archive:
            return ReprocessResult(record=record, ok=False, message=f"Cannot extract images for {record.note_id}: no local archive recorded.")

        metadata = _json_object(record.metadata_json)
        try:
            extracted = image_extract.extract_images_for_archive(Path(record.local_archive), record.source_kind, metadata)
        except Exception as exc:  # noqa: BLE001 - non-blocking
            return ReprocessResult(record=record, ok=False, message=f"Image extraction failed for {record.note_id}: {exc}")

        metadata["images"] = extracted
        metadata_json = json.dumps(metadata, ensure_ascii=True, sort_keys=True)
        updated = replace(record, metadata_json=metadata_json)
        self.database.update_note(updated)
        # Keep the on-disk metadata.json in step with the DB.
        try:
            (Path(record.local_archive) / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            pass
        return ReprocessResult(record=updated, ok=True, message=f"Extracted {len(extracted)} image(s) for {record.note_id}.")

    def extract_images_all(self) -> ExtractImagesAllSummary:
        """Backfill images for every fetched note from its archive. Non-blocking."""
        records = [r for r in self.database.list_notes_for_reindexing() if r.fetch_status == "fetched"]
        processed = 0
        total_images = 0
        errors: list[str] = []
        for record in records:
            try:
                result = self.extract_images(record.note_id)
            except Exception as exc:  # noqa: BLE001 - collect and continue
                errors.append(f"{record.note_id}: {exc}")
                continue
            if result.ok:
                processed += 1
                if result.record:
                    total_images += len(_json_object(result.record.metadata_json).get("images") or [])
            else:
                errors.append(f"{record.note_id}: {result.message}")
        return ExtractImagesAllSummary(total=len(records), processed=processed, images=total_images, errors=errors)

    def repersonalize(self, note_id: str) -> ReprocessResult:
        """Re-run only the personalization pass (call 2) for one note against the current
        profile. Cheap: no fetch, no re-summarize, no re-embed - the ground truth, tags,
        related links, and embedding are untouched."""
        record = self.database.find_by_note_id(note_id.strip().lower())
        if not record:
            return ReprocessResult(record=None, ok=False, message=f"No note found for {note_id}.")
        if not self.llm_config.is_configured:
            return ReprocessResult(record=record, ok=False, message="Personalization needs LLM_API_KEY and LLM_MODEL.")
        if record.llm_status != "generated":
            return ReprocessResult(record=record, ok=False, message=f"Cannot personalize {record.note_id}: LLM status is {record.llm_status}.")
        try:
            updated = self._apply_personalization(record, raise_on_error=True)
        except Exception as exc:  # noqa: BLE001 - report, keep the existing note intact
            return ReprocessResult(record=record, ok=False, message=f"Personalization failed: {exc}")
        self.database.update_note(updated)
        self._render_to_disk(updated)
        return ReprocessResult(record=updated, ok=True, message=f"Re-personalized: {updated.title}")

    def repersonalize_all(self) -> RepersonalizeSummary:
        """Re-run the personalization pass for every generated note (e.g. after a profile
        change). Non-blocking: one note's failure is collected, never aborts the batch."""
        if not self.llm_config.is_configured:
            return RepersonalizeSummary(total=0, updated=0, failed=0, errors=[])
        records = [r for r in self.database.list_notes_for_reindexing() if r.llm_status == "generated"]
        updated = 0
        errors: list[str] = []
        for record in records:
            try:
                refreshed = self._apply_personalization(record, raise_on_error=True)
            except Exception as exc:  # noqa: BLE001 - collect and continue
                errors.append(f"{record.note_id}: {exc}")
                continue
            self.database.update_note(refreshed)
            self._render_to_disk(refreshed)
            updated += 1
        return RepersonalizeSummary(total=len(records), updated=updated, failed=len(errors), errors=errors)

    def research_note(self, note_id: str) -> ReprocessResult:
        record = self.database.find_by_note_id(note_id.strip().lower())
        if not record:
            return ReprocessResult(record=None, ok=False, message=f"No note found for {note_id}.")
        if record.fetch_status != "fetched":
            return ReprocessResult(record=record, ok=False, message=f"Cannot research {record.note_id}: fetch status is {record.fetch_status}.")
        if not record.local_archive:
            return ReprocessResult(record=record, ok=False, message=f"Cannot research {record.note_id}: no local archive recorded.")

        extracted_path = Path(record.local_archive) / "extracted.txt"
        if not extracted_path.exists():
            return ReprocessResult(record=record, ok=False, message=f"Cannot research {record.note_id}: archived extracted.txt is missing.")

        extracted_text = extracted_path.read_text(encoding="utf-8")
        metadata = _json_object(record.metadata_json)
        if not extracted_text.strip() and record.local_archive:
            raw_path = Path(record.local_archive) / "raw.html"
            if raw_path.exists():
                _, recovered_text, recovered_metadata = extract_website_text(
                    raw_path.read_text(encoding="utf-8"),
                    record.resolved_url or record.source_url,
                    Path(record.local_archive),
                )
                if recovered_text.strip():
                    extracted_text = recovered_text
                    extracted_path.write_text(extracted_text, encoding="utf-8")
                    metadata = {**metadata, **recovered_metadata}

        requested_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        metadata = {**metadata, "research_status": "running", "research_requested_at": requested_at}
        working = replace(record, metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True))
        updated = self._apply_llm(working, extracted_text, metadata, force=True, web=True)

        metadata = _json_object(updated.metadata_json)
        if updated.llm_status == "generated":
            metadata.update({
                "research_status": "generated",
                "researched_at": updated.llm_generated_at or requested_at,
                "research_error": None,
            })
        else:
            metadata.update({
                "research_status": "failed",
                "research_error": updated.llm_error or updated.llm_status,
            })
        updated = replace(updated, metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True))

        note_path = self.vault_path / updated.note_path
        note_path.write_text(render_note(updated, extracted_text), encoding="utf-8")
        self.database.update_note(updated)
        updated = self._index_after_persist(updated)
        if updated.llm_status == "generated":
            return ReprocessResult(record=updated, ok=True, message=f"Researched: {updated.title}")
        return ReprocessResult(record=updated, ok=False, message=f"Research LLM {updated.llm_status}: {updated.llm_error or 'not generated'}")

    def retry_failed(self, limit: int = 25) -> RetryFailedResult:
        records = self.database.list_failed_notes(limit)
        retried = repaired = failed = skipped = 0
        messages: list[str] = []
        for record in records:
            if record.llm_status == "failed":
                retried += 1
                result = self.reprocess(record.note_id)
                if result.ok:
                    repaired += 1
                else:
                    failed += 1
                    messages.append(f"{record.note_id}: {result.message}")
                continue
            if record.embedding_status == "failed":
                retried += 1
                updated = self._index_after_persist(record)
                if updated.embedding_status == "indexed":
                    repaired += 1
                elif updated.embedding_status == "skipped":
                    skipped += 1
                    messages.append(f"{record.note_id}: embedding skipped")
                else:
                    failed += 1
                    messages.append(f"{record.note_id}: {updated.embedding_error or 'embedding failed'}")
        return RetryFailedResult(
            total=len(records),
            retried=retried,
            repaired=repaired,
            failed=failed,
            skipped=skipped,
            messages=messages[:5],
        )

    def delete_note(self, note_id: str) -> DeleteResult:
        record = self.database.find_by_note_id(note_id.strip().lower())
        if not record:
            return DeleteResult(ok=False, message=f"No note found for {note_id}.")
        _remove_path(self.vault_path / record.note_path, root=self.vault_path)
        if record.local_archive:
            _remove_path(Path(record.local_archive), root=self.archive_path)
        if self.indexer:
            try:
                self.indexer.delete_record(record.note_id)
            except Exception:
                pass
        self.database.delete_note(record.note_id)
        return DeleteResult(ok=True, message=f"Deleted note {record.note_id}: {record.title}", title=record.title)

    def rename_note(self, record: NoteRecord, new_title: str) -> NoteRecord:
        """Retitle a note in SQLite, rewrite its Markdown frontmatter, and re-embed.

        The title leads the canonical index text (see `canonical_index_text`), so
        a rename changes the embedding — re-index after persisting. Raises
        ValueError if the cleaned title is empty.
        """
        cleaned = clean_title(new_title)
        if not cleaned:
            raise ValueError("Title cannot be empty")
        updated = replace(record, title=cleaned)
        self.database.update_note(updated)
        self._render_to_disk(updated)
        return self._index_after_persist(updated)

    def set_status(self, record: NoteRecord, status: str) -> NoteRecord:
        """Set a note's review status in SQLite and rewrite its Markdown frontmatter.

        Status is not part of the embedded text, so no re-indexing is needed.
        Raises ValueError if `status` is not one of NOTE_STATUSES.
        """
        if status not in NOTE_STATUSES:
            raise ValueError(f"Status must be one of {', '.join(NOTE_STATUSES)}")
        changes: dict[str, object] = {"status": status}
        # Stamp when a note is first marked read so the feed can show "read 3d ago"
        # and time-based ordering/analytics work. Earlier reads aren't overwritten.
        if status == "reviewed" and not record.date_reviewed:
            changes["date_reviewed"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        updated = replace(record, **changes)
        self.database.update_note(updated)
        self._render_to_disk(updated)
        return updated

    def set_purpose(self, record: NoteRecord, purpose: str | None) -> NoteRecord:
        """Set a note's purpose classification in SQLite and rewrite its frontmatter.

        Purpose is not part of the embedded text (see `canonical_index_text`), so no
        re-indexing is needed. An empty/"none"/"unsorted" value clears the purpose;
        any other unrecognized value raises ValueError.
        """
        cleaned = (purpose or "").strip()
        if cleaned.lower() in ("", "none", "unsorted"):
            normalized: str | None = None
        else:
            normalized = normalize_purpose(cleaned)
            if normalized is None:
                raise ValueError(f"Purpose must be one of {', '.join(PURPOSE_VALUES)} (or none)")
        updated = replace(record, purpose=normalized)
        self.database.update_note(updated)
        self._render_to_disk(updated)
        return updated

    def apply_tags(self, record: NoteRecord, new_tags: list[str]) -> NoteRecord:
        """Set a note's tags in SQLite and rewrite its Markdown frontmatter in place.

        Used by the worker's tag-normalization pass and reusable elsewhere. The
        Markdown body is preserved by re-rendering with the archived extracted
        text. The semantic index is left as-is (tags feed embeddings but a plural
        merge barely changes them; rebuildable via `python -m prism.index rebuild`).
        """
        updated = replace(record, tags_json=json.dumps(new_tags, ensure_ascii=True))
        self.database.update_note(updated)
        self._render_to_disk(updated)
        return updated

    def remove_tag_everywhere(self, tag: str) -> int:
        """Delete a tag from every note that has it. Returns notes updated."""
        tag = tag.strip()
        if not tag:
            return 0
        count = 0
        for record in self.database.list_notes_with_tag(tag):
            self.apply_tags(record, [t for t in tags_for_record(record) if t != tag])
            count += 1
        return count

    def merge_tag(self, source: str, target: str) -> int:
        """Fold `source` tag into `target` across all notes. Returns notes updated."""
        source = source.strip()
        target = target.strip()
        if not source or not target or source == target:
            return 0
        count = 0
        for record in self.database.list_notes_with_tag(source):
            new_tags: list[str] = []
            for t in tags_for_record(record):
                replacement = target if t == source else t
                if replacement not in new_tags:
                    new_tags.append(replacement)
            self.apply_tags(record, new_tags)
            count += 1
        return count

    def merge_notes(self, keep_id: str, remove_id: str) -> MergeResult:
        """Consolidate two near-duplicate notes into the `keep` note, then delete `remove`.

        When the LLM is configured the kept note's content is regenerated as a
        synthesis of both sources (losing nothing from either); otherwise it
        degrades to a structural merge. Either way: tags and related-links are
        unioned, inbound backlinks are re-pointed remove→keep (no dangling refs),
        the kept note is re-embedded, and the duplicate is removed.
        """
        keep = self.database.find_by_note_id(keep_id.strip().lower())
        remove = self.database.find_by_note_id(remove_id.strip().lower())
        if not keep:
            return MergeResult(record=None, ok=False, message=f"Keep note {keep_id} not found.")
        if not remove:
            return MergeResult(record=keep, ok=False, message=f"Duplicate note {remove_id} not found (nothing to merge).")

        merged_tags = _dedup_preserve(tags_for_record(keep) + tags_for_record(remove))
        merged_related = _merge_related(keep, remove)
        metadata = _json_object(keep.metadata_json)
        merged_from = metadata.get("merged_from") if isinstance(metadata.get("merged_from"), list) else []
        metadata["merged_from"] = _dedup_preserve([*merged_from, remove.source_url])

        updated = keep
        synthesized = False
        if self.llm_config.is_configured:
            try:
                context = build_merge_context(notes=[self._merge_note_context(keep), self._merge_note_context(remove)])
                generation = LLMClient(self.llm_config).merge_notes(context, self.profile_path.read_text(encoding="utf-8"))
                structured = normalize_structured_summary(generation.data, [])
                structured["related_notes"] = merged_related
                structured["tags"] = merged_tags
                generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                updated = replace(
                    keep,
                    title=clean_title(_string_field(structured, "title")) or keep.title,
                    summary=_string_field(structured, "quick_summary") or keep.summary,
                    llm_status="generated",
                    llm_error=None,
                    llm_generated_at=generated_at,
                    llm_model=generation.model,
                    structured_summary_json=json.dumps(structured, ensure_ascii=True, sort_keys=True),
                    scores_json=json.dumps(_scores(structured), ensure_ascii=True, sort_keys=True),
                )
                synthesized = True
            except Exception:
                updated = keep  # fall back to structural merge below

        updated = replace(
            updated,
            tags_json=json.dumps(merged_tags, ensure_ascii=True),
            related_notes_json=json.dumps(merged_related, ensure_ascii=True, sort_keys=True),
            metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True),
        )
        self.database.update_note(updated)
        self._render_to_disk(updated)
        self._repoint_backlinks(remove.note_id, updated)
        self._index_after_persist(updated)
        self.delete_note(remove.note_id)

        how = "synthesized a merged note" if synthesized else "merged (structural; LLM unavailable)"
        return MergeResult(record=updated, ok=True, message=f"Merged {remove.note_id} into {updated.note_id}: {how}.", synthesized=synthesized)

    def _merge_note_context(self, record: NoteRecord) -> dict[str, Any]:
        structured = structured_summary(record)
        return {
            "id": record.note_id,
            "title": record.title,
            "source_url": record.source_url,
            "quick_summary": _string_field(structured, "quick_summary") or record.summary,
            "detailed_summary": _string_field(structured, "detailed_summary"),
            "key_claims": structured.get("key_claims") if isinstance(structured.get("key_claims"), list) else [],
            "tags": tags_for_record(record),
            "extracted_text": self._read_extracted(record)[:20000],
        }

    def _repoint_backlinks(self, old_id: str, target: NoteRecord) -> None:
        """Rewrite every other note's related-links that point at old_id to target instead."""
        for record in self.database.list_notes_for_reindexing():
            if record.note_id in {old_id, target.note_id}:
                continue
            related = related_notes_for_record(record)
            if not any(item["id"] == old_id for item in related):
                continue
            rewritten: list[dict[str, str]] = []
            seen: set[str] = set()
            for item in related:
                rid = item["id"]
                if rid == old_id:
                    item = {"id": target.note_id, "title": target.title, "reason": item.get("reason", "Related context."), "path": target.note_path}
                    rid = target.note_id
                if rid in seen:
                    continue
                seen.add(rid)
                rewritten.append(item)
            updated = replace(record, related_notes_json=json.dumps(rewritten, ensure_ascii=True, sort_keys=True))
            self.database.update_note(updated)
            self._render_to_disk(updated)

    def _read_extracted(self, record: NoteRecord) -> str:
        if record.local_archive:
            path = Path(record.local_archive) / "extracted.txt"
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except OSError:
                    return ""
        return ""

    def _render_to_disk(self, record: NoteRecord) -> None:
        try:
            (self.vault_path / record.note_path).write_text(render_note(record, self._read_extracted(record)), encoding="utf-8")
        except OSError:
            pass

    def wipe_all(self) -> WipeResult:
        note_count, idea_count = self.database.delete_all()
        _clear_directory(self.notes_path)
        _clear_directory(self.vault_path / "generated-ideas")
        _clear_directory(self.archive_path)
        if self.indexer:
            try:
                _clear_directory(self.indexer.lancedb_path)
            except Exception:
                pass
        return WipeResult(notes=note_count, ideas=idea_count)

    def reset_profile(self, user_input: str) -> ProfileResult:
        return self._rewrite_profile(user_input, mode="reset")

    def update_profile(self, user_input: str) -> ProfileResult:
        return self._rewrite_profile(user_input, mode="update")

    def _rewrite_profile(self, user_input: str, *, mode: str) -> ProfileResult:
        user_input = user_input.strip()
        if not user_input:
            return ProfileResult(ok=False, message="Add profile text after the command.")
        if not self.llm_config.is_configured:
            return ProfileResult(ok=False, message="Profile updates need LLM_API_KEY and LLM_MODEL.")
        ensure_profile(self.profile_path)
        current = self.profile_path.read_text(encoding="utf-8") if mode == "update" else None
        try:
            profile = LLMClient(self.llm_config).rewrite_profile(
                current_profile=current,
                user_input=user_input,
                mode=mode,
            )
        except Exception as exc:
            return ProfileResult(ok=False, message=f"Profile {mode} failed: {type(exc).__name__}: {exc}")
        self.profile_path.write_text(profile, encoding="utf-8")
        # The profile drives every note's personalization, so refresh it corpus-wide. Cheap:
        # each note is re-scored from its stored ground truth, never re-fetched or re-embedded.
        summary = self.repersonalize_all()
        message = f"Profile {mode} complete."
        if summary.total:
            message += f" Re-personalized {summary.updated}/{summary.total} notes."
            if summary.failed:
                message += f" {summary.failed} failed."
        return ProfileResult(ok=True, message=message, profile=profile)

    def search(self, query: str, limit: int = 20) -> list[RelatedCandidate]:
        """Hybrid note search: semantic (when configured) blended with keyword.

        Degrades to keyword-only when embeddings are unconfigured or semantic
        search fails, so it always returns useful results and never raises on a
        missing index. Used by /find across all front-ends; /ask reuses it for
        candidate gathering.
        """
        query = query.strip()
        if not query:
            return []
        semantic: list[RelatedCandidate] = []
        if self.indexer and self.indexer.is_configured:
            try:
                semantic = self.indexer.search_text(query, limit=limit)
            except Exception:  # noqa: BLE001 - fall back to keyword search
                semantic = []
        keyword = [
            _candidate_from_record(record, score=0.55)
            for record in self.database.search_notes_keyword(query, limit=limit)
        ]
        return _merge_candidates(semantic, keyword, limit=limit)

    def ask(self, question: str, limit: int = 6) -> AskResult:
        question = question.strip()
        if not question:
            return AskResult(answer="", sources=[], ok=False, message="Ask a question.")
        if not self.indexer or not self.indexer.is_configured:
            return AskResult(answer="", sources=[], ok=False, message="Semantic search is not configured.")
        if not self.llm_config.is_configured:
            return AskResult(answer="", sources=[], ok=False, message="/ask needs LLM_API_KEY and LLM_MODEL.")

        candidates = self.search(question, limit=limit)

        if not candidates:
            if self.indexer.index_is_empty():
                return AskResult(answer="", sources=[], ok=False, message="The semantic index is empty. Run: PYTHONPATH=src python -m prism.index rebuild")
            return AskResult(answer="", sources=[], ok=False, message="I have nothing saved about that.")

        context = build_ask_context(question=question, notes=[self._ask_note_context(c) for c in candidates])
        try:
            answer = LLMClient(self.llm_config).answer_question(context)
        except Exception as exc:
            return AskResult(answer="", sources=candidates, ok=False, message=f"Answer failed: {type(exc).__name__}: {exc}")
        if not answer:
            return AskResult(answer="", sources=candidates, ok=False, message="The model returned an empty answer.")
        return AskResult(answer=answer, sources=candidates, ok=True, message="")

    def _ask_note_context(self, candidate: RelatedCandidate) -> dict[str, Any]:
        record = self.database.find_by_note_id(candidate.note_id)
        structured = structured_summary(record) if record else {}
        quick = _string_field(structured, "quick_summary") or (record.summary if record else candidate.summary)
        detailed = _string_field(structured, "detailed_summary")
        claims = structured.get("key_claims")
        key_claims = [str(c).strip()[:ASK_CLAIM_LIMIT] for c in claims if str(c).strip()] if isinstance(claims, list) else []
        return {
            "id": candidate.note_id,
            "title": record.title if record else candidate.title,
            "quick_summary": _truncate(quick, ASK_QUICK_LIMIT),
            "detailed_summary": _truncate(detailed, ASK_DETAILED_LIMIT),
            "key_claims": key_claims[:5],
            "tags": tags_for_record(record) if record else candidate.tags,
            "source_url": record.source_url if record else candidate.source_url,
        }

    def _apply_llm(self, record: NoteRecord, extracted_text: str, metadata: dict[str, Any], force: bool = False, *, web: bool = False, related_candidates: list[RelatedCandidate] | None = None) -> NoteRecord:
        """Full note generation = ground-truth pass (call 1) then personalization (call 2)."""
        record = self._apply_ground_truth(record, extracted_text, metadata, force=force, web=web, related_candidates=related_candidates)
        if record.llm_status == "generated":
            # Personalization is non-blocking here: a ground-truth note still has value, so a
            # call-2 failure leaves the note un-personalized rather than failing the whole save.
            record = self._apply_personalization(record)
        return record

    def _apply_ground_truth(self, record: NoteRecord, extracted_text: str, metadata: dict[str, Any], force: bool = False, *, web: bool = False, related_candidates: list[RelatedCandidate] | None = None) -> NoteRecord:
        """Call 1: summarize the source objectively (profile-independent). Writes the
        ground-truth fields, tags, related_notes, and the novelty/credibility scores."""
        if record.fetch_status != "fetched":
            return replace(record, llm_status="skipped", llm_error="fetch did not succeed")
        if not self.llm_config.is_configured:
            return replace(record, llm_status="skipped", llm_error="LLM_API_KEY or LLM_MODEL is not configured")
        if not extracted_text.strip():
            return replace(record, llm_status="skipped", llm_error="no extracted text available")

        try:
            if related_candidates is None:
                related_candidates = self._related_candidates(record, extracted_text)
            context = build_llm_context(
                title=record.title,
                source_kind=record.source_kind,
                source_url=record.source_url,
                resolved_url=record.resolved_url,
                fetched_at=record.fetched_at,
                fetch_status=record.fetch_status,
                fetch_error=record.fetch_error,
                metadata=metadata,
                extracted_text=extracted_text,
                related_candidates=[candidate.to_llm_dict() for candidate in related_candidates],
            )
            if web:
                context["research_request"] = (
                    "Use OpenRouter web search to enrich this saved source with current, external context. "
                    "Keep the normal PRISM JSON shape, preserve uncertainty, and separate claims grounded in the "
                    "saved source from extra context discovered on the web."
                )
            generation = LLMClient(self.llm_config).generate_note(context, web=web)
            structured = normalize_structured_summary(generation.data, related_candidates)
            title = clean_title(_string_field(structured, "title")) or record.title
            summary = _string_field(structured, "quick_summary") or record.summary
            tags = _tags(structured.get("tags"))
            scores = _scores(structured)
            # Auto-classify into a single purpose; fall back to the existing value (or
            # Unsorted) when the LLM omits it or returns something unrecognized.
            purpose = normalize_purpose(structured.get("purpose")) or record.purpose
            generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            metadata_json = record.metadata_json
            if web and generation.web_sources:
                merged = {**metadata, "research_sources": generation.web_sources}
                metadata_json = json.dumps(merged, ensure_ascii=True, sort_keys=True)
            return replace(
                record,
                title=title,
                summary=summary,
                llm_status="generated",
                llm_error=None,
                llm_generated_at=generated_at,
                llm_model=generation.model,
                tags_json=json.dumps(tags, ensure_ascii=True),
                scores_json=json.dumps(scores, ensure_ascii=True, sort_keys=True),
                structured_summary_json=json.dumps(structured, ensure_ascii=True, sort_keys=True),
                related_notes_json=json.dumps(structured.get("related_notes", []), ensure_ascii=True, sort_keys=True),
                metadata_json=metadata_json,
                purpose=purpose,
            )
        except Exception as exc:
            if force or record.llm_status != "generated":
                return replace(record, llm_status="failed", llm_error=f"{type(exc).__name__}: {exc}"[:1000])
            return record

    def _apply_personalization(self, record: NoteRecord, *, raise_on_error: bool = False) -> NoteRecord:
        """Call 2: re-derive the reader-specific fields/scores from the note's ground truth
        + profile only (no source text). Merges them into the existing structured summary and
        scores, leaving summaries, tags, related_notes, and novelty/credibility untouched -
        so the embedding and graph never change. Safe to re-run when the profile changes."""
        if record.llm_status != "generated":
            return record
        if not self.llm_config.is_configured:
            return record
        try:
            structured = structured_summary(record)
            ground_truth = {key: structured.get(key) for key in GROUND_TRUTH_CONTEXT_FIELDS if structured.get(key) is not None}
            ground_truth.setdefault("title", record.title)
            ground_truth.setdefault("source_kind", record.source_kind)
            ground_truth.setdefault("source_url", record.source_url)
            ground_truth["tags"] = tags_for_record(record)
            generation = LLMClient(self.llm_config).personalize_note(
                ground_truth, self.profile_path.read_text(encoding="utf-8")
            )
            personal = generation.data
            new_structured = dict(structured)
            for key in PERSONAL_PROSE_FIELDS:
                if key in personal:
                    new_structured[key] = personal[key]
            personal_scores = _scores(personal)
            scores = scores_for_record(record)
            for key in PERSONAL_SCORE_FIELDS:
                if key in personal_scores:
                    scores[key] = personal_scores[key]
                    new_structured[key] = personal_scores[key]
            return replace(
                record,
                scores_json=json.dumps(scores, ensure_ascii=True, sort_keys=True),
                structured_summary_json=json.dumps(new_structured, ensure_ascii=True, sort_keys=True),
            )
        except Exception as exc:
            if raise_on_error:
                # Surface the failure to the caller but keep the existing (stale) note intact.
                raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
            return record

    def rediscover_on_this_day(self, limit: int = 12) -> list[NoteRecord]:
        """Notes saved on today's calendar day in previous periods."""
        month_day = datetime.now(UTC).strftime("%m-%d")
        return self.database.list_notes_on_day(month_day, limit)

    def rediscover_forgotten_gems(self, limit: int = 12, *, min_overall: float = 7.0, older_than_days: int = 30) -> list[NoteRecord]:
        """High-scoring notes that were saved a while ago and never reviewed."""
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).replace(microsecond=0)
        cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
        candidates = self.database.list_stale_unreviewed(cutoff_iso, limit=200)
        scored = [(r, scores_for_record(r).get("overall", 0) or 0) for r in candidates]
        gems = [r for r, score in scored if float(score) >= min_overall]
        gems.sort(key=lambda r: float(scores_for_record(r).get("overall", 0) or 0), reverse=True)
        return gems[:limit]

    def rediscover_related(self, note_id: str, limit: int = 8) -> list[RelatedCandidate]:
        """Live semantic neighbours of an existing note (distinct from stored related links)."""
        record = self.database.find_by_note_id(note_id.strip().lower())
        if not record or not self.indexer or not self.indexer.is_configured:
            return []
        try:
            return self.indexer.search_text(canonical_index_text(record), limit=limit, exclude_note_id=record.note_id)
        except Exception:
            return []

    def _related_candidates(self, record: NoteRecord, extracted_text: str) -> list[RelatedCandidate]:
        if not self.indexer or not self.indexer.is_configured:
            return []
        query = f"{canonical_index_text(record)}\nExtracted text: {extracted_preview(extracted_text)[:8000]}"
        try:
            return self.indexer.search_text(query, limit=10, exclude_note_id=record.note_id)
        except Exception:
            return []

    def _index_after_persist(self, record: NoteRecord) -> NoteRecord:
        if not self.indexer:
            return record
        result = self.indexer.index_record(record, self.database)
        return replace(
            record,
            embedding_status=result.status,
            embedding_error=result.error,
            embedded_at=result.embedded_at,
            embedding_model=result.model,
            embedding_dimensions=result.dimensions,
            embedding_text_hash=result.text_hash,
        )

    def _new_note_id(self) -> str:
        while True:
            note_id = secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:6].lower()
            if len(note_id) == 6 and not self.database.note_id_exists(note_id):
                return note_id

    def _unique_note_path(self, filename: str) -> Path:
        path = self.notes_path / filename
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        counter = 2
        while True:
            candidate = self.notes_path / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1


def _remove_path(path: Path, *, root: Path) -> None:
    try:
        target = path.resolve()
        base = root.resolve()
        if target != base and base not in target.parents:
            return
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    except OSError:
        pass


def _clear_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError:
            pass


def ensure_profile(profile_path: Path) -> None:
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if not profile_path.exists():
        profile_path.write_text(DEFAULT_PROFILE, encoding="utf-8")


def extract_first_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)\"]}'")


def placeholder_title(source_url: str) -> str:
    parsed = urlparse(source_url)
    host = parsed.netloc or "unknown-source"
    path_part = Path(parsed.path).stem if parsed.path else ""
    readable_path = slugify(path_part).replace("-", " ").strip()
    if readable_path:
        return f"Placeholder: {host} / {readable_path}"
    return f"Placeholder: {host}"


def clean_title(value: str | None) -> str | None:
    if not value:
        return None
    title = re.sub(r"\s+", " ", value).strip()
    return title[:200] if title else None


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:80] or "placeholder-title"


def summary_for_fetch(source_url: str, fetch: FetchResult) -> str:
    if fetch.fetch_status == "fetched":
        return f"Fetched {fetch.source_kind} capture for {source_url}"
    return f"Fetch failed for {source_url}: {fetch.fetch_error or 'unknown error'}"


def render_note(record: NoteRecord, extracted_text: str = "") -> str:
    structured = structured_summary(record)
    tags = tags_for_record(record)
    scores = scores_for_record(record)
    generated = record.llm_status == "generated"
    frontmatter = {
        "id": record.note_id,
        "title": record.title,
        "type": "source",
        "source_url": record.source_url,
        "resolved_url": record.resolved_url,
        "date_saved": record.date_saved,
        "date_processed": record.fetched_at,
        "source_kind": record.source_kind,
        "input_source": record.input_source,
        "local_archive": record.local_archive,
        "pdf_path": record.pdf_path,
        "content_hash": record.content_hash,
        "fetch_status": record.fetch_status,
        "fetch_error": record.fetch_error,
        "llm_status": record.llm_status,
        "llm_error": record.llm_error,
        "llm_generated_at": record.llm_generated_at,
        "llm_model": record.llm_model,
        "confidence": structured.get("confidence") if generated else None,
        "status": record.status,
        "purpose": record.purpose,
        "tags": tags,
        "relevance_score": scores.get("relevance"),
        "novelty_score": scores.get("novelty"),
        "credibility_score": scores.get("credibility"),
        "actionability_score": scores.get("actionability"),
        "interest_score": scores.get("interest"),
        "overall_score": scores.get("overall"),
        "summary_status": "generated" if generated else "placeholder",
        "related_notes": [item["id"] for item in related_notes_for_record(record)],
    }
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()

    if generated:
        body = render_generated_body(record, structured, extracted_text)
    else:
        body = render_fallback_body(record, extracted_text)
    return f"---\n{yaml_text}\n---\n\n{body}"


def render_generated_body(record: NoteRecord, structured: dict[str, Any], extracted_text: str) -> str:
    preview = extracted_preview(extracted_text) or "No extracted text available."
    return (
        f"# {record.title}\n\n"
        f"{_string_field(structured, 'quick_summary') or record.summary}\n\n"
        f"## Detailed Summary\n\n{_block_field(structured, 'detailed_summary')}\n\n"
        f"## Key Claims\n\n{_list_or_text(structured.get('key_claims'))}\n\n"
        f"## Limitations and Caveats\n\n{_list_or_text(structured.get('limitations'))}\n\n"
        f"## Technical Details\n\n{_list_or_text(structured.get('technical_details'))}\n\n"
        f"## Why It Matters\n\n{_block_field(structured, 'why_it_matters')}\n\n"
        f"## Personal Relevance\n\n{_block_field(structured, 'personal_relevance')}\n\n"
        f"## Possible Project Ideas\n\n{_list_or_text(structured.get('project_ideas'))}\n\n"
        f"## Related Notes\n\n{_related_note_lines(record)}\n\n"
        f"## Source\n\n{_source_lines(record)}\n\n"
        f"## Archive\n\n{_archive_lines(record)}\n\n"
        f"## Extracted Text Preview\n\n{preview}\n"
    )


def render_fallback_body(record: NoteRecord, extracted_text: str) -> str:
    preview = extracted_preview(extracted_text) or "No extracted text available."
    llm_line = f"- LLM status: {record.llm_status}"
    if record.llm_error:
        llm_line += f" ({record.llm_error})"
    return (
        f"# {record.title}\n\n"
        f"{record.summary}\n\n"
        f"## Source\n\n{_source_lines(record)}\n\n"
        f"## Archive\n\n{_archive_lines(record)}\n\n"
        f"## Extracted Text Preview\n\n{preview}\n\n"
        f"## Notes\n\n{llm_line}\n"
    )


def structured_summary(record: NoteRecord) -> dict[str, Any]:
    return _json_object(record.structured_summary_json)


def tags_for_record(record: NoteRecord) -> list[str]:
    data = _json_array(record.tags_json)
    return _tags(data)


def scores_for_record(record: NoteRecord) -> dict[str, float | int]:
    data = _json_object(record.scores_json)
    return _scores(data)


def more_summary_for_record(record: NoteRecord) -> str:
    structured = structured_summary(record)
    return _string_field(structured, "detailed_summary") or record.summary


def _candidate_from_record(record: NoteRecord, score: float) -> RelatedCandidate:
    return RelatedCandidate(
        note_id=record.note_id,
        title=record.title,
        summary=record.summary,
        note_path=record.note_path,
        source_url=record.source_url,
        tags=tags_for_record(record),
        score=score,
    )


def _merge_candidates(*groups: list[RelatedCandidate], limit: int) -> list[RelatedCandidate]:
    merged: list[RelatedCandidate] = []
    seen: set[str] = set()
    for group in groups:
        for candidate in group:
            if candidate.note_id in seen:
                continue
            merged.append(candidate)
            seen.add(candidate.note_id)
            if len(merged) >= limit:
                return merged
    return merged


def normalize_structured_summary(data: dict[str, Any], related_candidates: list[RelatedCandidate] | None = None) -> dict[str, Any]:
    normalized = dict(data)
    normalized["tags"] = _tags(normalized.get("tags"))
    if "purpose" in normalized:
        normalized["purpose"] = normalize_purpose(normalized.get("purpose"))
    normalized["related_notes"] = normalize_related_notes(normalized.get("related_notes"), related_candidates or [])
    for key, value in _scores(normalized).items():
        normalized[key] = value
    return normalized


def normalize_related_notes(value: Any, related_candidates: list[RelatedCandidate] | None = None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    candidates = {candidate.note_id: candidate for candidate in (related_candidates or [])}
    related: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id") or item.get("note_id") or "").strip().lower()
        if not note_id or note_id in seen:
            continue
        candidate = candidates.get(note_id)
        title = _clean_related_text(item.get("title")) or (candidate.title if candidate else note_id)
        reason = _clean_related_text(item.get("reason")) or "Related context."
        path = candidate.note_path if candidate else ""
        related.append({"id": note_id, "title": title, "reason": reason, "path": path, "origin": "llm"})
        seen.add(note_id)
    return related[:10]


def related_notes_for_record(record: NoteRecord) -> list[dict[str, Any]]:
    data = _json_array(record.related_notes_json)
    normalized: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or note_id).strip()
        reason = str(item.get("reason") or "Related context.").strip()
        path = str(item.get("path") or "").strip()
        origin = _related_origin(item.get("origin"))
        if note_id:
            entry: dict[str, Any] = {"id": note_id, "title": title, "reason": reason, "path": path, "origin": origin}
            similarity = _related_similarity(item.get("similarity"))
            if similarity is not None:
                entry["similarity"] = similarity
            normalized.append(entry)
    return normalized


def _related_origin(value: object) -> str:
    origin = str(value or "llm").strip().lower()
    if origin in {"auto", "llm", "manual"}:
        return origin
    return "unknown"


def _related_similarity(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        similarity = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(similarity):
        return None
    return round(min(max(similarity, 0.0), 1.0), 4)


def _dedup_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _merge_related(keep: NoteRecord, remove: NoteRecord) -> list[dict[str, str]]:
    """Union both notes' related-links, dropping references to the two merged notes."""
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in related_notes_for_record(keep) + related_notes_for_record(remove):
        rid = item["id"]
        if rid in seen or rid in {keep.note_id, remove.note_id}:
            continue
        seen.add(rid)
        merged.append(item)
    return merged


def _truncate(text: str, limit: int) -> str:
    if not text or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def extracted_preview(text: str) -> str:
    preview = re.sub(r"\s+", " ", text).strip()
    if len(preview) > PREVIEW_LIMIT:
        return preview[:PREVIEW_LIMIT].rstrip() + "..."
    return preview


def _related_note_lines(record: NoteRecord) -> str:
    items = related_notes_for_record(record)
    if not items:
        return "None selected."
    lines: list[str] = []
    for item in items:
        stem = Path(item.get("path") or item["title"]).stem or item["id"]
        lines.append(f"- [[{stem}|{item['title']}]] - {item['reason']}")
    return "\n".join(lines)


def _clean_related_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:300]


def _source_lines(record: NoteRecord) -> str:
    return (
        f"- URL: {record.source_url}\n"
        f"- Resolved URL: {record.resolved_url}\n"
        f"- Saved: {record.date_saved}\n"
        f"- Fetched: {record.fetched_at or 'Not fetched'}"
    )


def _archive_lines(record: NoteRecord) -> str:
    lines = [
        f"- Local archive: {record.local_archive or 'None'}",
        f"- PDF: {record.pdf_path or 'None'}",
        f"- Content hash: {record.content_hash or 'None'}",
        f"- Fetch status: {record.fetch_status}",
    ]
    if record.fetch_error:
        lines.append(f"- Fetch error: {record.fetch_error}")
    return "\n".join(lines)


def _string_field(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def _block_field(data: dict[str, Any], key: str) -> str:
    return _string_field(data, key) or "Not provided."


def _list_or_text(value: Any) -> str:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(f"- {item}" for item in items) or "Not provided."
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "Not provided."


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = re.sub(r"[^a-z0-9-]+", "-", str(item).lower().lstrip("#")).strip("-")
        if tag and tag not in tags:
            tags.append(tag[:50])
    return tags[:12]


def _scores(data: dict[str, Any]) -> dict[str, float | int]:
    scores: dict[str, float | int] = {}
    for key in SCORE_FIELDS:
        value = data.get(key)
        number: float | None = None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                number = None
        if number is None:
            continue
        # Guard against an out-of-range value from the model (the rubric is 1-10).
        number = max(1.0, min(10.0, number))
        scores[key] = int(number) if number.is_integer() else number
    return scores


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_array(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


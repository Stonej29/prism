"""Periodic graph maintenance (additive + proposals).

Auto-applied (safe, non-destructive — no approval needed):
  * refresh_related_links — recompute each note's *automatic* semantic-neighbour
    links from scratch (a bounded, fresh top-K), while preserving the original
    LLM-chosen links from note creation. Because it recomputes rather than
    appends, links stay current instead of piling up.
  * normalize_tags — merge near-duplicate tags across the corpus
    (e.g. foundation-model / foundation-models) onto a single canonical form.

Proposed for human review (never auto-applied):
  * detect_duplicate_proposals — flag near-duplicate note pairs as `merge`
    proposals, written to the proposals table for approval via bot/web.

Similarity is cosine over the stored embedding vectors, independent of the
LanceDB search metric. The corpus is small (tens–hundreds of notes), so an
O(n^2) pass is fine; the job runs at most weekly.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from datetime import UTC, datetime

from prism.db import ProposalRecord
from prism.proposals import KIND_MERGE, new_proposal_id
from prism.services import Services
from prism.worker.config import TraversalSettings

LOGGER = logging.getLogger(__name__)

MAX_PROPOSALS_PER_RUN = 25
AUTO_ORIGIN = "auto"           # marks links this job manages (vs. LLM-chosen ones)
TraversalEventEmitter = Callable[[dict[str, Any]], None]


@dataclass
class TraversalSummary:
    notes: int = 0
    links_added: int = 0
    links_removed: int = 0
    notes_relinked: int = 0
    tags_merged: int = 0
    notes_retagged: int = 0
    duplicates_proposed: int = 0


def run_graph_traversal(
    services: Services,
    settings: TraversalSettings | None = None,
    emit_event: TraversalEventEmitter | None = None,
) -> TraversalSummary:
    indexer = services.indexer
    summary = TraversalSummary()
    settings = settings or TraversalSettings()
    _emit(emit_event, "phase", phase="tags", message="Normalizing tags")

    # Tag normalization needs only SQLite, so it runs even without embeddings.
    _normalize_tags(services, summary, emit_event)

    if not indexer or not indexer.is_configured:
        LOGGER.info("Graph traversal: embeddings not configured; did tags only")
        _emit(emit_event, "phase", phase="complete", message="Embeddings not configured; tags only")
        return summary

    _emit(emit_event, "phase", phase="links", message="Refreshing related-note links")
    vectors = indexer.all_vectors()
    ids = list(vectors)
    summary.notes = len(ids)
    if len(ids) >= 2:
        sim = _similarity_matrix([vectors[i] for i in ids])
        records = {nid: services.database.find_by_note_id(nid) for nid in ids}
        _refresh_related_links(services, ids, sim, records, summary, settings, emit_event)
        _emit(emit_event, "phase", phase="duplicates", message="Detecting near-duplicate notes")
        _detect_duplicate_proposals(services, ids, sim, records, summary, settings, emit_event)

    LOGGER.info(
        "Graph traversal: %d notes; links +%d/-%d across %d notes; tags merged %d across %d notes; %d duplicate proposals",
        summary.notes, summary.links_added, summary.links_removed, summary.notes_relinked,
        summary.tags_merged, summary.notes_retagged, summary.duplicates_proposed,
    )
    return summary


# --- auto: related links (recompute, never pile up) -------------------------

def _refresh_related_links(
    services,
    ids,
    sim,
    records,
    summary: TraversalSummary,
    settings: TraversalSettings,
    emit_event: TraversalEventEmitter | None = None,
) -> None:
    for i, note_id in enumerate(ids):
        record = records.get(note_id)
        if record is None:
            continue
        raw = _raw_related(record)
        kept = [item for item in raw if item.get("origin") != AUTO_ORIGIN]
        kept_ids = {str(item.get("id")) for item in kept} | {note_id}
        prev_auto_ids = {str(item.get("id")) for item in raw if item.get("origin") == AUTO_ORIGIN}

        auto: list[dict] = []
        slots = min(settings.max_auto_links, settings.max_links_per_note - len(kept))
        for score, other_id in sorted(
            ((sim[i][j], ids[j]) for j in range(len(ids)) if j != i),
            key=lambda pair: pair[0],
            reverse=True,
        ):
            if len(auto) >= slots or score < settings.link_threshold:
                break
            if other_id in kept_ids:
                continue
            other = records.get(other_id)
            if other is None:
                continue
            auto.append({
                "id": other_id,
                "title": other.title,
                "reason": f"Semantically related (similarity {score:.2f}).",
                "similarity": round(float(score), 4),
                "path": other.note_path,
                "origin": AUTO_ORIGIN,
            })

        new_auto_ids = {item["id"] for item in auto}
        if new_auto_ids == prev_auto_ids:
            continue  # no change to the auto set
        merged = kept + auto
        services.database.update_related_notes(note_id, json.dumps(merged, ensure_ascii=True, sort_keys=True))
        added = new_auto_ids - prev_auto_ids
        removed = prev_auto_ids - new_auto_ids
        summary.links_added += len(added)
        summary.links_removed += len(removed)
        summary.notes_relinked += 1
        for target_id in sorted(added):
            _emit(emit_event, "edge_added", source=note_id, target=target_id, origin=AUTO_ORIGIN)
        for target_id in sorted(removed):
            _emit(emit_event, "edge_removed", source=note_id, target=target_id, origin=AUTO_ORIGIN)
        _emit(emit_event, "note_relinked", note_id=note_id, origin=AUTO_ORIGIN, links_added=len(added), links_removed=len(removed))


# --- auto: tag normalization ------------------------------------------------

def _normalize_tags(services, summary: TraversalSummary, emit_event: TraversalEventEmitter | None = None) -> None:
    mapping = build_canonical_tag_map(services.database.list_tags_with_counts())
    if not mapping:
        return
    summary.tags_merged = len(mapping)
    for record in services.database.list_notes_for_reindexing():
        tags = _record_tags(record)
        if not tags:
            continue
        remapped: list[str] = []
        for tag in tags:
            canonical = mapping.get(tag, tag)
            if canonical not in remapped:
                remapped.append(canonical)
        if remapped != tags:
            services.notes.apply_tags(record, remapped)
            summary.notes_retagged += 1
            _emit(emit_event, "note_retagged", note_id=record.note_id, tags=remapped)


def build_canonical_tag_map(tag_counts: list[tuple[str, int]]) -> dict[str, str]:
    """Map each near-duplicate tag to its canonical form. Only changed tags appear.

    Tags are grouped by a normalized key (separators removed, simple
    de-pluralization); within a group the most-used surface form wins
    (tie-break: shortest, then alphabetical).
    """
    groups: dict[str, list[tuple[str, int]]] = {}
    for tag, count in tag_counts:
        groups.setdefault(_tag_key(tag), []).append((tag, count))
    mapping: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        canonical = sorted(members, key=lambda tc: (-tc[1], len(tc[0]), tc[0]))[0][0]
        for tag, _ in members:
            if tag != canonical:
                mapping[tag] = canonical
    return mapping


def _tag_key(tag: str) -> str:
    key = tag.replace("-", "").replace("_", "")
    if key.endswith("ies") and len(key) > 4:
        return key[:-3] + "y"
    if key.endswith("s") and not key.endswith("ss") and len(key) > 3:
        return key[:-1]
    return key


# --- proposals: near-duplicate notes ----------------------------------------

def _detect_duplicate_proposals(
    services,
    ids,
    sim,
    records,
    summary: TraversalSummary,
    settings: TraversalSettings,
    emit_event: TraversalEventEmitter | None = None,
) -> None:
    created = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if created >= MAX_PROPOSALS_PER_RUN:
                summary.duplicates_proposed = created
                return
            if sim[i][j] < settings.dup_threshold:
                continue
            keep_id, remove_id = _rank_pair(ids[i], ids[j], records)
            note_ids_json = json.dumps(sorted([keep_id, remove_id]), ensure_ascii=True)
            if services.database.pending_proposal_exists(KIND_MERGE, note_ids_json):
                continue
            keep, remove = records.get(keep_id), records.get(remove_id)
            payload = {
                "keep": keep_id,
                "remove": remove_id,
                "keep_title": keep.title if keep else keep_id,
                "remove_title": remove.title if remove else remove_id,
                "similarity": round(float(sim[i][j]), 4),
            }
            proposal_id = new_proposal_id(services.database)
            services.database.insert_proposal(ProposalRecord(
                proposal_id=proposal_id,
                created_at=_now(),
                kind=KIND_MERGE,
                status="pending",
                note_ids_json=note_ids_json,
                payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
            ))
            _emit(emit_event, "proposal_created", proposal_id=proposal_id, keep=keep_id, remove=remove_id, similarity=payload["similarity"])
            created += 1
    summary.duplicates_proposed = created


def _rank_pair(a: str, b: str, records) -> tuple[str, str]:
    """Return (keep_id, remove_id): keep higher overall score, tie-break earlier save."""
    ra, rb = records.get(a), records.get(b)
    if ra is None or rb is None:
        return a, b
    sa, sb = _overall(ra), _overall(rb)
    if sa != sb:
        return (a, b) if sa > sb else (b, a)
    return (a, b) if (ra.date_saved or "") <= (rb.date_saved or "") else (b, a)


# --- helpers ----------------------------------------------------------------

def _emit(emit_event: TraversalEventEmitter | None, kind: str, **payload: Any) -> None:
    if emit_event is not None:
        emit_event({"kind": kind, **payload})


def _raw_related(record) -> list[dict]:
    if not record.related_notes_json:
        return []
    try:
        data = json.loads(record.related_notes_json)
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


def _record_tags(record) -> list[str]:
    from prism.notes import tags_for_record

    return tags_for_record(record)


def _overall(record) -> float:
    from prism.notes import scores_for_record

    return float(scores_for_record(record).get("overall") or 0.0)


def _similarity_matrix(vectors: list[list[float]]) -> list[list[float]]:
    try:
        import numpy as np

        matrix = np.asarray(vectors, dtype="float64")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = matrix / norms
        return (normalized @ normalized.T).tolist()
    except Exception:
        return _similarity_matrix_py(vectors)


def _similarity_matrix_py(vectors: list[list[float]]) -> list[list[float]]:
    import math

    normalized = []
    for vec in vectors:
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        normalized.append([x / norm for x in vec])
    n = len(normalized)
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            dot = sum(a * b for a, b in zip(normalized[i], normalized[j]))
            sim[i][j] = sim[j][i] = dot
    return sim


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

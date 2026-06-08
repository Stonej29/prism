"""Build the note graph payload (nodes + edges + clusterings) for the center pane.

Nodes are notes; edges are the *semantic* (`origin == "auto"`) related-links only
(deduped undirected, dangling refs dropped) -- these are the real graph
relationships. LLM-suggested "similar notes" stay in each note's detail payload
and are NOT drawn as graph edges. Each node carries two cluster assignments:
- `topic`     -- k-means over embedding vectors (semantic similarity)
- `community` -- label-propagation over the semantic-link graph
The graph exposes topic, score, and semantic-link similarity separately so the
frontend can encode them with independent visual channels.
"""
from __future__ import annotations

import math
import re
from typing import Any

from prism.db import NoteRecord
from prism.notes import related_notes_for_record, scores_for_record, tags_for_record
from prism.web.clustering import cluster_labels, kmeans_clusters, link_communities


ORIGIN_ORDER = {"auto": 0, "llm": 1, "manual": 2, "unknown": 3}
SIMILARITY_RE = re.compile(r"similarity\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)


def link_origin(value: object) -> str:
    origin = str(value or "llm").strip().lower()
    return origin if origin in ORIGIN_ORDER else "unknown"


def build_graph(records: list[NoteRecord], vectors: dict[str, list[float]] | None = None, source_filter: str | None = None) -> dict[str, Any]:
    vectors = vectors or {}
    notes = [r for r in records if source_filter is None or r.source_kind == source_filter]
    id_set = {r.note_id for r in notes}
    ids = [r.note_id for r in notes]
    tags_by_id = {r.note_id: tags_for_record(r) for r in notes}

    # Dedupe undirected related-links across all origins (corpus stat), keeping
    # the strongest origin per pair (auto < llm < manual). Only `auto` pairs
    # become drawn graph edges; the rest stay as "similar notes" in the detail
    # pane and are counted in links_by_origin for maintenance reporting.
    pair_origin: dict[tuple[str, str], str] = {}
    auto_reason: dict[tuple[str, str], str] = {}
    auto_similarity: dict[tuple[str, str], float] = {}
    for r in notes:
        for rel in related_notes_for_record(r):
            target = rel.get("id", "")
            if target not in id_set:
                continue
            a, b = sorted((r.note_id, target))
            if a == b:
                continue
            origin = link_origin(rel.get("origin"))
            prev = pair_origin.get((a, b))
            if prev is None or ORIGIN_ORDER[origin] < ORIGIN_ORDER[prev]:
                pair_origin[(a, b)] = origin
            if origin == "auto":
                if (a, b) not in auto_reason:
                    auto_reason[(a, b)] = rel.get("reason", "")
                similarity = _related_similarity(rel)
                if similarity is not None:
                    previous = auto_similarity.get((a, b))
                    if previous is None or similarity > previous:
                        auto_similarity[(a, b)] = similarity

    edges: list[dict[str, Any]] = []
    for (a, b), origin in pair_origin.items():
        if origin != "auto":
            continue
        edge: dict[str, Any] = {"source": a, "target": b, "reason": auto_reason.get((a, b), ""), "origin": "auto"}
        similarity = auto_similarity.get((a, b))
        if similarity is not None:
            edge["similarity"] = similarity
        edges.append(edge)
    edge_pairs = [(e["source"], e["target"]) for e in edges]

    topic = kmeans_clusters(ids, vectors)
    community = link_communities(ids, edge_pairs)
    topic_labels = cluster_labels(topic, tags_by_id)

    nodes: list[dict[str, Any]] = []
    for r in notes:
        scores = scores_for_record(r)
        nodes.append({
            "id": r.note_id,
            "title": r.title,
            "source_kind": r.source_kind,
            "status": r.status,
            "date_saved": r.date_saved,
            "overall": scores.get("overall"),
            "favorite": bool(r.favorite),
            "failed": r.fetch_status == "failed" or r.llm_status == "failed",
            "tags": tags_by_id[r.note_id],
            "topic": topic.get(r.note_id, -1),
            "community": community.get(r.note_id, -1),
        })

    n_topics = len(set(topic.values())) if topic else 0
    n_comm = len(set(community.values())) if community else 0
    return {
        "nodes": nodes,
        "edges": edges,
        "topic_labels": {str(k): v for k, v in topic_labels.items()},
        "counts": {
            "notes": len(nodes),
            "links": len(edges),
            "topics": n_topics,
            "communities": n_comm,
            "links_by_origin": _origin_counts(pair_origin),
        },
    }


def link_origin_counts(records: list[NoteRecord]) -> dict[str, int]:
    graph = build_graph(records, vectors={})
    return graph["counts"]["links_by_origin"]


def _related_similarity(rel: dict[str, Any]) -> float | None:
    raw = rel.get("similarity")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return _clamped_similarity(float(raw))
    if isinstance(raw, str):
        try:
            return _clamped_similarity(float(raw))
        except ValueError:
            pass

    # Backward compatibility for auto-links created before similarity was a
    # structured field. New data should use the numeric `similarity` key above.
    match = SIMILARITY_RE.search(str(rel.get("reason") or ""))
    if match:
        try:
            return _clamped_similarity(float(match.group(1)))
        except ValueError:
            return None
    return None


def _clamped_similarity(value: float) -> float | None:
    if not math.isfinite(value):
        return None
    return round(min(max(value, 0.0), 1.0), 4)


def _origin_counts(pair_origin: dict[tuple[str, str], str]) -> dict[str, int]:
    counts = {origin: 0 for origin in ORIGIN_ORDER}
    for origin in pair_origin.values():
        counts[origin] += 1
    return counts

"""Build the note graph payload (nodes + edges + clusterings) for the center pane.

Nodes are notes; edges come from each note's `related_notes_json` (deduped
undirected, dangling refs dropped). Each node carries two cluster assignments:
- `topic`     — k-means over embedding vectors (semantic similarity)
- `community` — label-propagation over auto links when available, otherwise
  over the full related-note graph
Node color still encodes `source_kind`; clustering is independent.
"""
from __future__ import annotations

from typing import Any

from prism.db import NoteRecord
from prism.notes import related_notes_for_record, scores_for_record, tags_for_record
from prism.web.clustering import cluster_labels, kmeans_clusters, link_communities


ORIGIN_ORDER = {"auto": 0, "llm": 1, "manual": 2, "unknown": 3}


def link_origin(value: object) -> str:
    origin = str(value or "llm").strip().lower()
    return origin if origin in ORIGIN_ORDER else "unknown"


def build_graph(records: list[NoteRecord], vectors: dict[str, list[float]] | None = None, source_filter: str | None = None) -> dict[str, Any]:
    vectors = vectors or {}
    notes = [r for r in records if source_filter is None or r.source_kind == source_filter]
    id_set = {r.note_id for r in notes}
    ids = [r.note_id for r in notes]
    tags_by_id = {r.note_id: tags_for_record(r) for r in notes}

    seen: set[tuple[str, str]] = set()
    edges: list[dict[str, Any]] = []
    edge_pairs: list[tuple[str, str]] = []
    for r in notes:
        for rel in related_notes_for_record(r):
            target = rel.get("id", "")
            if target not in id_set:
                continue
            a, b = sorted((r.note_id, target))
            origin = link_origin(rel.get("origin"))
            if a == b or (a, b) in seen:
                if (a, b) in seen:
                    _merge_edge_origin(edges, a, b, origin)
                continue
            seen.add((a, b))
            edges.append({"source": a, "target": b, "reason": rel.get("reason", ""), "origin": origin})
            edge_pairs.append((a, b))

    topic = kmeans_clusters(ids, vectors)
    auto_edge_pairs = [(e["source"], e["target"]) for e in edges if link_origin(e.get("origin")) == "auto"]
    community = link_communities(ids, auto_edge_pairs or edge_pairs)
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
            "job_relevant": bool(r.job_relevant),
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
            "links_by_origin": _origin_counts(edges),
        },
    }


def link_origin_counts(records: list[NoteRecord]) -> dict[str, int]:
    graph = build_graph(records, vectors={})
    return graph["counts"]["links_by_origin"]


def _merge_edge_origin(edges: list[dict[str, Any]], source: str, target: str, origin: str) -> None:
    for edge in edges:
        if edge["source"] == source and edge["target"] == target:
            current = link_origin(edge.get("origin"))
            if ORIGIN_ORDER[origin] < ORIGIN_ORDER[current]:
                edge["origin"] = origin
            return


def _origin_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts = {origin: 0 for origin in ORIGIN_ORDER}
    for edge in edges:
        counts[link_origin(edge.get("origin"))] += 1
    return counts

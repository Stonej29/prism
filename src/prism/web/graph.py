"""Build the note graph payload (nodes + edges + clusterings) for the center pane.

Nodes are notes; edges come from each note's `related_notes_json` (deduped
undirected, dangling refs dropped). Each node carries two cluster assignments:
- `topic`     — k-means over embedding vectors (semantic similarity)
- `community` — label-propagation over the link graph (explicit relatedness)
Node color still encodes `source_kind`; clustering is independent.
"""
from __future__ import annotations

from typing import Any

from prism.db import NoteRecord
from prism.notes import related_notes_for_record, scores_for_record, tags_for_record
from prism.web.clustering import cluster_labels, kmeans_clusters, link_communities


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
            if a == b or (a, b) in seen:
                continue
            seen.add((a, b))
            edges.append({"source": a, "target": b, "reason": rel.get("reason", "")})
            edge_pairs.append((a, b))

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
        "counts": {"notes": len(nodes), "links": len(edges), "topics": n_topics, "communities": n_comm},
    }

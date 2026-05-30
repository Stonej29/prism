"""Build the note graph payload (nodes + edges + clusters) for the center pane.

Nodes are notes; edges come from each note's `related_notes_json` (the
LLM-selected related notes), deduplicated as undirected pairs, with dangling
references (targets that aren't in the node set) dropped. Clusters default to
`source_kind`.
"""
from __future__ import annotations

from typing import Any

from prism.db import NoteRecord
from prism.notes import related_notes_for_record, scores_for_record, tags_for_record


def build_graph(records: list[NoteRecord], source_filter: str | None = None) -> dict[str, Any]:
    notes = [r for r in records if source_filter is None or r.source_kind == source_filter]
    id_set = {r.note_id for r in notes}

    nodes: list[dict[str, Any]] = []
    for r in notes:
        scores = scores_for_record(r)
        nodes.append(
            {
                "id": r.note_id,
                "title": r.title,
                "source_kind": r.source_kind,
                "overall": scores.get("overall"),
                "tags": tags_for_record(r),
                "cluster": r.source_kind,
            }
        )

    seen: set[tuple[str, str]] = set()
    edges: list[dict[str, Any]] = []
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

    clusters = sorted({node["cluster"] for node in nodes})
    return {
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "counts": {"notes": len(nodes), "links": len(edges), "clusters": len(clusters)},
    }

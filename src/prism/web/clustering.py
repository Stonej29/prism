"""Topic clustering (k-means over embeddings) and link-community detection.

Both produce a {note_id: cluster_index} mapping. Topic clusters reflect
semantic similarity; link communities reflect the explicit related-note graph.
"""
from __future__ import annotations

import math
from collections import Counter


def auto_k(n: int) -> int:
    """Heuristic cluster count ~ sqrt(n/2), clamped to [1, 8]."""
    if n <= 1:
        return 1
    return max(1, min(8, round(math.sqrt(n / 2)) or 1))


def kmeans_clusters(ids: list[str], vectors: dict[str, list[float]], *, iters: int = 50, seed: int = 0) -> dict[str, int]:
    import numpy as np

    pts = [(i, vectors[i]) for i in ids if i in vectors]
    if not pts:
        return {}
    pid = [i for i, _ in pts]
    X = np.asarray([v for _, v in pts], dtype=float)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    X = X / norms  # L2-normalize → euclidean k-means approximates cosine

    n = len(pid)
    k = max(1, min(auto_k(n), n))
    rng = np.random.default_rng(seed)
    centroids = X[rng.choice(n, k, replace=False)].copy()
    labels = np.full(n, -1)
    for it in range(iters):
        d = ((X[:, None, :] - centroids[None, :, :]) ** 2).sum(-1)
        new = d.argmin(1)
        if it > 0 and np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            mask = labels == j
            if mask.any():
                centroids[j] = X[mask].mean(0)
    return {pid[i]: int(labels[i]) for i in range(n)}


def link_communities(node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Label-propagation communities over the related-note link graph."""
    adj: dict[str, set[str]] = {i: set() for i in node_ids}
    for s, t in edges:
        if s in adj and t in adj:
            adj[s].add(t)
            adj[t].add(s)
    label = {i: idx for idx, i in enumerate(node_ids)}
    for _ in range(30):
        changed = False
        for i in node_ids:  # deterministic order
            if not adj[i]:
                continue
            counts: dict[int, int] = {}
            for nb in adj[i]:
                counts[label[nb]] = counts.get(label[nb], 0) + 1
            best = min((-c, lbl) for lbl, c in counts.items())[1]  # max count, tie → smallest label
            if label[i] != best:
                label[i] = best
                changed = True
        if not changed:
            break
    remap = {lbl: idx for idx, lbl in enumerate(sorted(set(label.values())))}
    return {i: remap[label[i]] for i in node_ids}


def cluster_labels(assignment: dict[str, int], tags_by_id: dict[str, list[str]]) -> dict[int, str]:
    """Label each cluster by its most common member tags."""
    groups: dict[int, Counter] = {}
    for nid, c in assignment.items():
        groups.setdefault(c, Counter()).update(tags_by_id.get(nid, []))
    labels: dict[int, str] = {}
    for c, counter in groups.items():
        top = [t for t, _ in counter.most_common(2)]
        labels[c] = " · ".join(top) if top else f"cluster {c + 1}"
    return labels

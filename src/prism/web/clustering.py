"""Topic clustering (k-means over embeddings) and link-community detection.

Both produce a {note_id: cluster_index} mapping. Topic clusters reflect
semantic similarity; link communities reflect the explicit related-note graph.
"""
from __future__ import annotations

import math
from collections import Counter


GENERIC_LABEL_TAGS = frozenset({
    "open-source",
    "apache-2-0",
    "mit-license",
    "github",
    "python",
    "self-hosted",
    "dataset",
    "benchmark",
    "web-demo",
})


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
    """Label clusters with frequent, distinctive member tags."""
    groups: dict[int, Counter] = {}
    cluster_presence: dict[str, set[int]] = {}
    for nid, c in assignment.items():
        tags = tags_by_id.get(nid, [])
        groups.setdefault(c, Counter()).update(tags)
        for tag in set(tags):
            cluster_presence.setdefault(tag, set()).add(c)

    labels: dict[int, str] = {}
    cluster_count = max(len(groups), 1)
    for c, counter in groups.items():
        top = _rank_cluster_tags(counter, cluster_presence, cluster_count, allow_generic=False)[:2]
        if len(top) < 2:
            for tag in _rank_cluster_tags(counter, cluster_presence, cluster_count, allow_generic=True):
                if tag not in top:
                    top.append(tag)
                if len(top) >= 2:
                    break
        labels[c] = " · ".join(top) if top else f"cluster {c + 1}"
    return labels


def _rank_cluster_tags(
    counter: Counter,
    cluster_presence: dict[str, set[int]],
    cluster_count: int,
    *,
    allow_generic: bool,
) -> list[str]:
    scored: list[tuple[float, int, int, str]] = []
    for tag, count in counter.items():
        if not tag:
            continue
        generic = tag in GENERIC_LABEL_TAGS
        if generic and not allow_generic:
            continue
        spread = len(cluster_presence.get(tag, set())) or 1
        specificity = max(0.0, math.log((cluster_count + 1) / (spread + 0.5)))
        score = float(count) * (1.0 + specificity)
        if generic:
            score *= 0.2
        scored.append((-score, spread, -int(count), tag))
    scored.sort()
    return [tag for _, _, _, tag in scored]

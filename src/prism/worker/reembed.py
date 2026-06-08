"""Stale-embedding detection + re-embed pass.

Each note stores the SHA-256 (`embedding_text_hash`) of the canonical index text
it was last embedded from. When a note is edited (rename, retag, reprocess,
merge) its index text changes but a re-embed may not have run. This pass
recomputes the hash for every note and re-embeds only those whose stored hash no
longer matches — far cheaper than a full `python -m prism.index rebuild`.

No-op when no indexer is configured.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from prism.index import canonical_index_text, hash_text
from prism.services import Services

LOGGER = logging.getLogger("prism.worker.reembed")


@dataclass
class ReembedSummary:
    checked: int = 0
    stale: int = 0
    reindexed: int = 0
    failed: int = 0


def run_reembed(services: Services) -> ReembedSummary:
    summary = ReembedSummary()
    indexer = services.indexer
    if not indexer or not indexer.is_configured:
        LOGGER.info("Re-embed skipped: embeddings are not configured")
        return summary

    for record in services.database.list_notes_for_reindexing():
        summary.checked += 1
        current = hash_text(canonical_index_text(record))
        if current == record.embedding_text_hash:
            continue
        summary.stale += 1
        result = indexer.index_record(record, services.database)
        if result.status == "indexed":
            summary.reindexed += 1
        elif result.status == "failed":
            summary.failed += 1
    LOGGER.info(
        "Re-embed complete: %d checked, %d stale, %d reindexed, %d failed",
        summary.checked, summary.stale, summary.reindexed, summary.failed,
    )
    return summary

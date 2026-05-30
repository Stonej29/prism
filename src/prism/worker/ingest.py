"""Scheduled feed ingestion: pull feed items and push them through save_url.

Dedup is delegated to `NoteService.save_url` (source_url, then content_hash), so
re-polling the same feed never creates duplicate notes. Every failure is
isolated per feed and per item so one bad entry can't abort the run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from prism.notes import NoteService
from prism.worker.config import FeedSpec
from prism.worker.feeds import feed_item_urls

LOGGER = logging.getLogger(__name__)


@dataclass
class IngestionSummary:
    feeds: int = 0
    seen: int = 0
    created: int = 0
    duplicates: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def run_feed_ingestion(notes: NoteService, feeds: list[FeedSpec]) -> IngestionSummary:
    summary = IngestionSummary(feeds=len(feeds))
    for spec in feeds:
        try:
            urls = feed_item_urls(spec)
        except Exception as exc:
            summary.failed += 1
            summary.errors.append(f"{spec.url}: {type(exc).__name__}: {exc}")
            LOGGER.warning("Feed fetch failed for %s: %s", spec.url, exc)
            continue
        for url in urls:
            summary.seen += 1
            try:
                result = notes.save_url(url, spec.input_source)
            except Exception as exc:
                summary.failed += 1
                summary.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                LOGGER.warning("Ingest failed for %s: %s", url, exc)
                continue
            if result.created:
                summary.created += 1
            else:
                summary.duplicates += 1
    LOGGER.info(
        "Feed ingestion: %d feeds, %d seen, %d created, %d duplicates, %d failed",
        summary.feeds, summary.seen, summary.created, summary.duplicates, summary.failed,
    )
    return summary

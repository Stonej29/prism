from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism.notes import SaveResult
from prism.worker.config import (
    DEFAULT_INGESTION_CRON,
    DEFAULT_TRAVERSAL_CRON,
    FeedSpec,
    load_worker_config,
    parse_worker_config,
)
from prism.worker.feeds import feed_item_urls
from prism.worker.ingest import run_feed_ingestion

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>AI Search</title>
  <item><title>A</title><link>https://ex.com/a</link></item>
  <item><title>B</title><link>https://ex.com/b</link></item>
  <item><title>B dup</title><link>https://ex.com/b</link></item>
  <item><title>C</title><link>https://ex.com/c</link></item>
</channel></rss>"""


class WorkerConfigTests(unittest.TestCase):
    def test_parses_feeds_and_schedule(self) -> None:
        cfg = parse_worker_config({
            "feeds": [
                {"type": "rss", "url": "https://a.com/feed", "max": 5},
                {"type": "rss", "url": "https://b.com/feed", "input_source": "scheduled"},
                {"type": "rss"},  # no url -> dropped
                "garbage",         # not a dict -> dropped
            ],
            "schedule": {"ingestion": "0 6 * * *", "traversal": "0 9 * * 1"},
            "traversal_enabled": True,
        })
        self.assertEqual(len(cfg.feeds), 2)
        self.assertEqual(cfg.feeds[0], FeedSpec(type="rss", url="https://a.com/feed", max_items=5))
        self.assertEqual(cfg.feeds[1].input_source, "scheduled")
        self.assertEqual(cfg.ingestion_cron, "0 6 * * *")
        self.assertEqual(cfg.traversal_cron, "0 9 * * 1")
        self.assertTrue(cfg.traversal_enabled)

    def test_missing_file_yields_defaults(self) -> None:
        cfg = load_worker_config(Path("/nonexistent/feeds.yaml"))
        self.assertEqual(cfg.feeds, [])
        self.assertEqual(cfg.ingestion_cron, DEFAULT_INGESTION_CRON)
        self.assertEqual(cfg.traversal_cron, DEFAULT_TRAVERSAL_CRON)
        self.assertFalse(cfg.traversal_enabled)

    def test_loads_from_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feeds.yaml"
            path.write_text(
                "feeds:\n  - type: rss\n    url: https://aisearch.substack.com/feed\n    max: 3\n",
                encoding="utf-8",
            )
            cfg = load_worker_config(path)
            self.assertEqual(len(cfg.feeds), 1)
            self.assertEqual(cfg.feeds[0].url, "https://aisearch.substack.com/feed")
            self.assertEqual(cfg.feeds[0].max_items, 3)

    def test_malformed_yaml_yields_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feeds.yaml"
            path.write_text("just a string", encoding="utf-8")
            cfg = load_worker_config(path)
            self.assertEqual(cfg.feeds, [])


class FeedAdapterTests(unittest.TestCase):
    def test_rss_returns_links_deduped_and_capped(self) -> None:
        def fake_get(url, headers=None):
            return RSS, url, "application/rss+xml"

        spec = FeedSpec(type="rss", url="https://ex.com/feed", max_items=10)
        urls = feed_item_urls(spec, get_bytes=fake_get)
        self.assertEqual(urls, ["https://ex.com/a", "https://ex.com/b", "https://ex.com/c"])

        capped = feed_item_urls(FeedSpec(type="rss", url="https://ex.com/feed", max_items=2), get_bytes=fake_get)
        self.assertEqual(capped, ["https://ex.com/a", "https://ex.com/b"])

    def test_unknown_feed_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            feed_item_urls(FeedSpec(type="atomish", url="https://ex.com/feed"), get_bytes=lambda *a, **k: (b"", "", None))


class _FakeNotes:
    def __init__(self, behaviors: dict[str, str]) -> None:
        self.behaviors = behaviors
        self.calls: list[tuple[str, str]] = []

    def save_url(self, url: str, input_source: str = "telegram") -> SaveResult:
        self.calls.append((url, input_source))
        behavior = self.behaviors.get(url, "created")
        if behavior == "raise":
            raise RuntimeError("save boom")
        return SaveResult(
            record=None,  # type: ignore[arg-type]
            created=(behavior == "created"),
            duplicate_reason=None if behavior == "created" else "source_url",
        )


class IngestionTests(unittest.TestCase):
    def test_counts_created_duplicate_failed(self) -> None:
        notes = _FakeNotes({"https://ex.com/a": "created", "https://ex.com/b": "dup", "https://ex.com/c": "raise"})
        feeds = [FeedSpec(type="rss", url="https://ex.com/feed", max_items=10, input_source="ai_search")]
        with patch(
            "prism.worker.ingest.feed_item_urls",
            return_value=["https://ex.com/a", "https://ex.com/b", "https://ex.com/c"],
        ):
            summary = run_feed_ingestion(notes, feeds)
        self.assertEqual(summary.feeds, 1)
        self.assertEqual(summary.seen, 3)
        self.assertEqual(summary.created, 1)
        self.assertEqual(summary.duplicates, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(notes.calls[0], ("https://ex.com/a", "ai_search"))

    def test_feed_fetch_failure_is_isolated(self) -> None:
        notes = _FakeNotes({})
        feeds = [FeedSpec(type="rss", url="https://bad.com/feed")]
        with patch("prism.worker.ingest.feed_item_urls", side_effect=RuntimeError("dns")):
            summary = run_feed_ingestion(notes, feeds)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.seen, 0)
        self.assertEqual(notes.calls, [])


if __name__ == "__main__":
    unittest.main()

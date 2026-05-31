"""Worker configuration loaded from a YAML file (default `/data/feeds.yaml`).

The file lives in the shared `runtime/` volume so feeds and schedules can be
edited without rebuilding the image. Missing or malformed config degrades to an
empty feed list with sensible default schedules — the worker still starts.

Example `feeds.yaml`:

    feeds:
      - type: rss
        url: https://aisearch.substack.com/feed
        max: 10
    schedule:
      ingestion: "0 7 * * *"     # daily 07:00
      traversal: "0 8 * * 0"     # weekly, Sunday 08:00
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_INGESTION_CRON = "0 7 * * *"
DEFAULT_TRAVERSAL_CRON = "0 5 * * 1"  # weekly, Monday 05:00
DEFAULT_BACKUP_CRON = "0 2 * * *"  # daily 02:00
DEFAULT_REEMBED_CRON = "0 3 * * 0"  # weekly, Sunday 03:00
DEFAULT_TIMEZONE = "Europe/Copenhagen"
DEFAULT_MAX_ITEMS = 10


@dataclass(frozen=True)
class FeedSpec:
    type: str
    url: str
    max_items: int = DEFAULT_MAX_ITEMS
    posts: int = 3  # digest feeds only: how many newest posts to expand into their read-more links
    input_source: str = "ai_search"


@dataclass(frozen=True)
class WorkerConfig:
    feeds: list[FeedSpec] = field(default_factory=list)
    ingestion_cron: str = DEFAULT_INGESTION_CRON
    traversal_cron: str = DEFAULT_TRAVERSAL_CRON
    backup_cron: str = DEFAULT_BACKUP_CRON
    reembed_cron: str = DEFAULT_REEMBED_CRON
    timezone: str = DEFAULT_TIMEZONE
    traversal_enabled: bool = False
    backup_enabled: bool = False
    reembed_enabled: bool = False


def feeds_path_from_env() -> Path:
    return Path(os.getenv("PRISM_FEEDS_PATH", "/data/feeds.yaml"))


def load_worker_config(path: Path | None = None) -> WorkerConfig:
    path = path or feeds_path_from_env()
    if not path.exists():
        return WorkerConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return WorkerConfig()
    if not isinstance(raw, dict):
        return WorkerConfig()
    return parse_worker_config(raw)


def parse_worker_config(raw: dict) -> WorkerConfig:
    feeds = [spec for spec in (_parse_feed(item) for item in _as_list(raw.get("feeds"))) if spec]
    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    return WorkerConfig(
        feeds=feeds,
        ingestion_cron=_str(schedule.get("ingestion"), DEFAULT_INGESTION_CRON),
        traversal_cron=_str(schedule.get("traversal"), DEFAULT_TRAVERSAL_CRON),
        backup_cron=_str(schedule.get("backup"), DEFAULT_BACKUP_CRON),
        reembed_cron=_str(schedule.get("reembed"), DEFAULT_REEMBED_CRON),
        timezone=_str(schedule.get("timezone"), DEFAULT_TIMEZONE),
        traversal_enabled=bool(raw.get("traversal_enabled", False)),
        backup_enabled=bool(raw.get("backup_enabled", False)),
        reembed_enabled=bool(raw.get("reembed_enabled", False)),
    )


def _parse_feed(item: object) -> FeedSpec | None:
    if not isinstance(item, dict):
        return None
    url = _str(item.get("url"), "")
    if not url:
        return None
    feed_type = _str(item.get("type"), "rss").lower()
    try:
        max_items = max(1, int(item.get("max", DEFAULT_MAX_ITEMS)))
    except (TypeError, ValueError):
        max_items = DEFAULT_MAX_ITEMS
    try:
        posts = max(1, int(item.get("posts", 3)))
    except (TypeError, ValueError):
        posts = 3
    return FeedSpec(
        type=feed_type,
        url=url,
        max_items=max_items,
        posts=posts,
        input_source=_str(item.get("input_source"), "ai_search"),
    )


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _str(value: object, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default

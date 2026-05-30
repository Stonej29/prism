"""Feed adapters: turn a feed spec into a list of candidate item URLs.

Adapters fetch via `prism.fetch._http_get_bytes` (shared User-Agent, timeout,
and size cap) rather than letting libraries do their own HTTP, which keeps
fetching consistent and makes the adapters testable by patching that one call.
"""
from __future__ import annotations

from collections.abc import Callable

from prism.fetch import _http_get_bytes
from prism.worker.config import FeedSpec

GetBytes = Callable[..., tuple[bytes, str, str | None]]


def feed_item_urls(spec: FeedSpec, *, get_bytes: GetBytes = _http_get_bytes) -> list[str]:
    """Return up to spec.max_items candidate URLs for the given feed."""
    if spec.type == "rss":
        return _rss_item_urls(spec, get_bytes=get_bytes)
    raise ValueError(f"Unsupported feed type: {spec.type}")


def _rss_item_urls(spec: FeedSpec, *, get_bytes: GetBytes) -> list[str]:
    import feedparser

    raw, _, _ = get_bytes(spec.url)
    parsed = feedparser.parse(raw)
    urls: list[str] = []
    seen: set[str] = set()
    for entry in parsed.entries:
        link = _entry_link(entry)
        if not link or link in seen:
            continue
        seen.add(link)
        urls.append(link)
        if len(urls) >= spec.max_items:
            break
    return urls


def _entry_link(entry: object) -> str | None:
    link = getattr(entry, "get", lambda *_: None)("link")
    if isinstance(link, str) and link.strip():
        return link.strip()
    return None

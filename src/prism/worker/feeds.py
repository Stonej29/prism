"""Feed adapters: turn a feed spec into a list of candidate item URLs.

Adapters fetch via `prism.fetch._http_get_bytes` (shared User-Agent, timeout,
and size cap) rather than letting libraries do their own HTTP, which keeps
fetching consistent and makes the adapters testable by patching that one call.
"""
from __future__ import annotations

from collections.abc import Callable

from prism.fetch import _http_get_bytes, extract_read_more_links
from prism.worker.config import FeedSpec

GetBytes = Callable[..., tuple[bytes, str, str | None]]

# Safety cap on links pulled from a digest feed in one run.
MAX_DIGEST_LINKS = 80


def feed_item_urls(spec: FeedSpec, *, get_bytes: GetBytes = _http_get_bytes) -> list[str]:
    """Return the candidate item URLs to ingest for the given feed.

    - rss: each entry's own link (up to max_items).
    - digest: open the newest `posts` entries and return their "Read more" link
      targets (the underlying repos/papers/sites), not the posts themselves.
    """
    if spec.type == "rss":
        return _rss_entry_links(spec.url, spec.max_items, get_bytes=get_bytes)
    if spec.type == "digest":
        return _digest_item_urls(spec, get_bytes=get_bytes)
    raise ValueError(f"Unsupported feed type: {spec.type}")


def _rss_entry_links(feed_url: str, limit: int, *, get_bytes: GetBytes) -> list[str]:
    import feedparser

    raw, _, _ = get_bytes(feed_url)
    parsed = feedparser.parse(raw)
    urls: list[str] = []
    seen: set[str] = set()
    for entry in parsed.entries:
        link = _entry_link(entry)
        if not link or link in seen:
            continue
        seen.add(link)
        urls.append(link)
        if len(urls) >= limit:
            break
    return urls


def _digest_item_urls(spec: FeedSpec, *, get_bytes: GetBytes) -> list[str]:
    post_urls = _rss_entry_links(spec.url, spec.posts, get_bytes=get_bytes)
    out: list[str] = []
    seen: set[str] = set()
    for post_url in post_urls:
        try:
            raw, resolved, _ = get_bytes(post_url)
        except Exception:
            continue
        html = raw.decode("utf-8", errors="replace")
        for link in extract_read_more_links(html, resolved or post_url):
            if link in seen:
                continue
            seen.add(link)
            out.append(link)
            if len(out) >= MAX_DIGEST_LINKS:
                return out
    return out


def _entry_link(entry: object) -> str | None:
    link = getattr(entry, "get", lambda *_: None)("link")
    if isinstance(link, str) and link.strip():
        return link.strip()
    return None

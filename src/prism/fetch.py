from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from xml.etree import ElementTree

from prism.config import (
    DEFAULT_FETCH_MAX_DOWNLOAD_BYTES,
    DEFAULT_FETCH_MAX_REDIRECTS,
    DEFAULT_FETCH_RETRY_ATTEMPTS,
    DEFAULT_FETCH_RETRY_BACKOFF_BASE,
    DEFAULT_FETCH_TIMEOUT_SECONDS,
    load_fetch_settings,
)

LOGGER = logging.getLogger(__name__)

# Browser-like headers: many sites (Cloudflare etc.) 403 a bare bot UA. Sending a
# realistic UA + Accept headers recovers most "Fetch failed / 403" captures.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
FETCH_TIMEOUT_SECONDS = DEFAULT_FETCH_TIMEOUT_SECONDS
MAX_DOWNLOAD_BYTES = DEFAULT_FETCH_MAX_DOWNLOAD_BYTES
FETCH_RETRY_ATTEMPTS = DEFAULT_FETCH_RETRY_ATTEMPTS
FETCH_RETRY_BACKOFF_BASE = DEFAULT_FETCH_RETRY_BACKOFF_BASE
MAX_REDIRECTS = DEFAULT_FETCH_MAX_REDIRECTS
# Hard-block statuses where retrying the same request won't help; we surface them
# clearly (and fall back to a reader proxy for websites) instead of retrying.
_BLOCKED_STATUSES = {401, 403, 451}
# r.jina.ai is a free reader proxy that fetches + extracts a page server-side;
# used only as a fallback when the origin hard-blocks our request.
JINA_READER_PREFIX = "https://r.jina.ai/"


class FetchBlockedError(Exception):
    """Raised when an origin hard-blocks the request (401/403/451)."""

    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"Blocked by server (HTTP {status_code})")


@dataclass(frozen=True)
class FetchResult:
    source_url: str
    resolved_url: str
    source_kind: str
    title: str | None
    summary: str | None
    extracted_text: str
    local_archive: str | None
    pdf_path: str | None
    content_hash: str | None
    fetch_status: str
    fetch_error: str | None
    fetched_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


def fetch_source(source_url: str, archive_root: Path, note_id: str) -> FetchResult:
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    archive_dir = archive_root / note_id
    source_kind = detect_source_kind(source_url)
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        if source_kind == "paper" and parse_arxiv_id(source_url):
            return _fetch_arxiv(source_url, archive_dir, fetched_at)
        if source_kind == "github":
            return _fetch_github_repo(source_url, archive_dir, fetched_at)
        if source_kind == "pdf":
            return _fetch_pdf(source_url, archive_dir, fetched_at, source_kind="pdf")
        if source_kind == "youtube":
            return _fetch_youtube(source_url, archive_dir, fetched_at)
        if source_kind == "huggingface":
            return _fetch_huggingface(source_url, archive_dir, fetched_at)
        return _fetch_website(source_url, archive_dir, fetched_at)
    except Exception as exc:  # Fetch failures should still produce a note.
        metadata = {"source_url": source_url, "error_type": type(exc).__name__}
        _write_json(archive_dir / "metadata.json", metadata)
        return FetchResult(
            source_url=source_url,
            resolved_url=source_url,
            source_kind=source_kind,
            title=None,
            summary=None,
            extracted_text="",
            local_archive=str(archive_dir),
            pdf_path=None,
            content_hash=None,
            fetch_status="failed",
            fetch_error=str(exc)[:1000],
            fetched_at=fetched_at,
            metadata=metadata,
        )


def detect_source_kind(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host in {"arxiv.org", "www.arxiv.org"} and (path.startswith("/abs/") or path.startswith("/pdf/")):
        return "paper"
    if path.endswith(".pdf"):
        return "pdf"
    if parse_youtube_id(url):
        return "youtube"
    if host in {"huggingface.co", "www.huggingface.co"} and _hf_kind(url):
        return "huggingface"
    if host == "github.com" and _github_owner_repo(url):
        return "github"
    if parsed.scheme in {"http", "https"}:
        return "website"
    return "unknown"


def parse_youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/")[0]
        return video_id or None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        path = parsed.path
        if path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            return video_id or None
        match = re.match(r"/(?:shorts|embed|live|v)/([^/?#]+)", path)
        if match:
            return match.group(1) or None
    return None


def parse_arxiv_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"arxiv.org", "www.arxiv.org"}:
        return None
    match = re.match(r"/(?:abs|pdf)/(.+)", parsed.path)
    if not match:
        return None
    arxiv_id = match.group(1).removesuffix(".pdf")
    return arxiv_id or None


def _fetch_arxiv(source_url: str, archive_dir: Path, fetched_at: str) -> FetchResult:
    arxiv_id = parse_arxiv_id(source_url)
    if not arxiv_id:
        raise ValueError("Could not parse arXiv ID")

    metadata_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    metadata_resolved = metadata_url
    metadata_error = None
    try:
        metadata_bytes, metadata_resolved, _ = _http_get_bytes(metadata_url)
        entry = _parse_arxiv_atom(metadata_bytes)
    except Exception as exc:
        entry = {}
        metadata_error = f"{type(exc).__name__}: {exc}"[:1000]

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_bytes, pdf_resolved, pdf_content_type = _http_get_bytes(pdf_url)

    pdf_path = archive_dir / "source.pdf"
    pdf_path.write_bytes(pdf_bytes)
    pdf_text, pdf_meta = _extract_pdf(pdf_bytes)
    extracted = "\n\n".join(part for part in [entry.get("summary"), pdf_text] if part).strip()

    # Title cascade: arXiv metadata > clean PDF /Title > URL stem.
    url_title = _title_from_url(pdf_resolved)
    pdf_title = _clean_pdf_title(pdf_meta.get("title"), url_title)
    if entry.get("title"):
        title, title_source = entry["title"], "arxiv"
    elif pdf_title:
        title, title_source = pdf_title, "pdf_meta"
    else:
        title, title_source = url_title, "url"

    metadata = {
        "source_url": source_url,
        "metadata_url": metadata_resolved,
        "metadata_error": metadata_error,
        "pdf_url": pdf_resolved,
        "content_type": pdf_content_type,
        "arxiv_id": arxiv_id,
        "title_source": title_source,
        **_pdf_metadata_fields(pdf_meta),
        **entry,
    }
    _write_text(archive_dir / "extracted.txt", extracted)
    _write_json(archive_dir / "metadata.json", metadata)
    return FetchResult(
        source_url=source_url,
        resolved_url=pdf_resolved,
        source_kind="paper",
        title=title,
        summary=entry.get("summary"),
        extracted_text=extracted,
        local_archive=str(archive_dir),
        pdf_path=str(pdf_path),
        content_hash=content_hash(extracted, fallback_bytes=pdf_bytes),
        fetch_status="fetched",
        fetch_error=None,
        fetched_at=fetched_at,
        metadata=metadata,
    )


def _fetch_pdf(source_url: str, archive_dir: Path, fetched_at: str, source_kind: str) -> FetchResult:
    pdf_bytes, resolved_url, content_type = _http_get_bytes(source_url)
    pdf_path = archive_dir / "source.pdf"
    pdf_path.write_bytes(pdf_bytes)
    extracted, pdf_meta = _extract_pdf(pdf_bytes)
    url_title = _title_from_url(resolved_url)
    pdf_title = _clean_pdf_title(pdf_meta.get("title"), url_title)
    title = pdf_title or url_title
    metadata = {
        "source_url": source_url,
        "resolved_url": resolved_url,
        "content_type": content_type,
        "title_source": "pdf_meta" if pdf_title else "url",
        **_pdf_metadata_fields(pdf_meta),
    }
    _write_text(archive_dir / "extracted.txt", extracted)
    _write_json(archive_dir / "metadata.json", metadata)
    return FetchResult(
        source_url=source_url,
        resolved_url=resolved_url,
        source_kind=source_kind,
        title=title,
        summary=None,
        extracted_text=extracted,
        local_archive=str(archive_dir),
        pdf_path=str(pdf_path),
        content_hash=content_hash(extracted, fallback_bytes=pdf_bytes),
        fetch_status="fetched",
        fetch_error=None,
        fetched_at=fetched_at,
        metadata=metadata,
    )


def fetch_upload(
    data: bytes,
    filename: str,
    archive_root: Path,
    note_id: str,
    content_type: str | None = None,
) -> FetchResult:
    """Build a FetchResult from uploaded bytes (e.g. a Telegram document), no URL fetch."""
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    archive_dir = archive_root / note_id
    safe_name = filename.strip() or "upload"
    hashed = content_hash("", fallback_bytes=data) or hashlib.sha256(data or b"").hexdigest()
    source_url = f"upload://{hashed[:16]}/{slugify_filename(safe_name)}"
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        max_download_bytes = load_fetch_settings().max_download_bytes
        if len(data) > max_download_bytes:
            raise ValueError(f"Upload exceeded {max_download_bytes} byte limit")
        is_pdf = (content_type or "").lower().startswith("application/pdf") or safe_name.lower().endswith(".pdf")
        if not is_pdf:
            raise ValueError(f"Unsupported upload type: {content_type or safe_name}")
        pdf_path = archive_dir / "source.pdf"
        pdf_path.write_bytes(data)
        extracted, pdf_meta = _extract_pdf(data)
        name_title = _title_from_filename(safe_name)
        pdf_title = _clean_pdf_title(pdf_meta.get("title"), name_title)
        title = pdf_title or name_title
        metadata = {
            "source_url": source_url,
            "filename": safe_name,
            "content_type": content_type,
            "upload": True,
            "title_source": "pdf_meta" if pdf_title else "filename",
            **_pdf_metadata_fields(pdf_meta),
        }
        _write_text(archive_dir / "extracted.txt", extracted)
        _write_json(archive_dir / "metadata.json", metadata)
        return FetchResult(
            source_url=source_url,
            resolved_url=source_url,
            source_kind="pdf",
            title=title,
            summary=None,
            extracted_text=extracted,
            local_archive=str(archive_dir),
            pdf_path=str(pdf_path),
            content_hash=content_hash(extracted, fallback_bytes=data),
            fetch_status="fetched",
            fetch_error=None,
            fetched_at=fetched_at,
            metadata=metadata,
        )
    except Exception as exc:
        metadata = {"source_url": source_url, "filename": safe_name, "error_type": type(exc).__name__, "upload": True}
        _write_json(archive_dir / "metadata.json", metadata)
        return FetchResult(
            source_url=source_url,
            resolved_url=source_url,
            source_kind="pdf",
            title=_title_from_filename(safe_name),
            summary=None,
            extracted_text="",
            local_archive=str(archive_dir),
            pdf_path=None,
            content_hash=content_hash("", fallback_bytes=data),
            fetch_status="failed",
            fetch_error=str(exc)[:1000],
            fetched_at=fetched_at,
            metadata=metadata,
        )


def _fetch_github_repo(source_url: str, archive_dir: Path, fetched_at: str) -> FetchResult:
    owner_repo = _github_owner_repo(source_url)
    if not owner_repo:
        raise ValueError("GitHub URL is not a repository URL")
    owner, repo = owner_repo

    repo_meta = _fetch_github_repo_metadata(owner, repo)

    api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    data_bytes, resolved_url, content_type = _http_get_bytes(api_url, headers={"Accept": "application/vnd.github+json"})
    data = json.loads(data_bytes.decode("utf-8"))
    if data.get("encoding") == "base64" and data.get("content"):
        readme_bytes = base64.b64decode(data["content"])
    elif data.get("download_url"):
        readme_bytes, _, _ = _http_get_bytes(data["download_url"])
    else:
        raise ValueError("GitHub README response did not include readable content")

    readme_text = readme_bytes.decode("utf-8", errors="replace")
    _write_text(archive_dir / "readme.md", readme_text)

    header = _github_metadata_header(owner, repo, repo_meta)
    extracted_text = f"{header}\n\n{readme_text}" if repo_meta else readme_text

    metadata = {
        "source_url": source_url,
        "resolved_url": resolved_url,
        "content_type": content_type,
        "owner": owner,
        "repo": repo,
        "readme_name": data.get("name"),
        "readme_path": data.get("path"),
        "html_url": data.get("html_url"),
        **{f"repo_{k}": v for k, v in repo_meta.items()},
    }
    _write_text(archive_dir / "extracted.txt", extracted_text)
    _write_json(archive_dir / "metadata.json", metadata)
    return FetchResult(
        source_url=source_url,
        resolved_url=f"https://github.com/{owner}/{repo}",
        source_kind="github",
        title=f"{owner}/{repo}",
        summary=repo_meta.get("description"),
        extracted_text=extracted_text,
        local_archive=str(archive_dir),
        pdf_path=None,
        content_hash=content_hash(extracted_text, fallback_bytes=readme_bytes),
        fetch_status="fetched",
        fetch_error=None,
        fetched_at=fetched_at,
        metadata=metadata,
    )


def _fetch_github_repo_metadata(owner: str, repo: str) -> dict[str, Any]:
    try:
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        data_bytes, _, _ = _http_get_bytes(api_url, headers={"Accept": "application/vnd.github+json"})
        data = json.loads(data_bytes.decode("utf-8"))
        result: dict[str, Any] = {}
        if isinstance(data.get("description"), str) and data["description"]:
            result["description"] = data["description"]
        if isinstance(data.get("stargazers_count"), int):
            result["stars"] = data["stargazers_count"]
        if isinstance(data.get("license"), dict) and data["license"].get("spdx_id"):
            result["license"] = data["license"]["spdx_id"]
        if isinstance(data.get("pushed_at"), str):
            result["last_pushed"] = data["pushed_at"][:10]
        if isinstance(data.get("language"), str) and data["language"]:
            result["language"] = data["language"]
        if isinstance(data.get("topics"), list):
            result["topics"] = [t for t in data["topics"] if isinstance(t, str)]
        return result
    except Exception:
        return {}


def _github_metadata_header(owner: str, repo: str, meta: dict[str, Any]) -> str:
    lines = [f"Repository: {owner}/{repo}"]
    if meta.get("description"):
        lines.append(f"Description: {meta['description']}")
    if meta.get("stars") is not None:
        lines.append(f"Stars: {meta['stars']}")
    if meta.get("language"):
        lines.append(f"Language: {meta['language']}")
    if meta.get("license"):
        lines.append(f"License: {meta['license']}")
    if meta.get("last_pushed"):
        lines.append(f"Last updated: {meta['last_pushed']}")
    if meta.get("topics"):
        lines.append(f"Topics: {', '.join(meta['topics'])}")
    return "\n".join(lines)


def _fetch_youtube(source_url: str, archive_dir: Path, fetched_at: str) -> FetchResult:
    video_id = parse_youtube_id(source_url)
    if not video_id:
        raise ValueError("Could not parse YouTube video id")

    metadata: dict[str, Any] = {"source_url": source_url, "video_id": video_id}
    title: str | None = None
    summary: str | None = None
    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        oembed_bytes, _, _ = _http_get_bytes(oembed_url)
        oembed = json.loads(oembed_bytes.decode("utf-8"))
        title = oembed.get("title")
        metadata["author_name"] = oembed.get("author_name")
        metadata["author_url"] = oembed.get("author_url")
        summary = oembed.get("title")
    except Exception as exc:
        metadata["oembed_error"] = f"{type(exc).__name__}: {exc}"[:500]

    transcript_text = ""
    try:
        transcript_text = _youtube_transcript(video_id)
        if transcript_text:
            _write_text(archive_dir / "transcript.txt", transcript_text)
    except Exception as exc:
        metadata["transcript_error"] = f"{type(exc).__name__}: {exc}"[:500]

    header_lines = [f"YouTube video: {title or video_id}"]
    if metadata.get("author_name"):
        header_lines.append(f"Channel: {metadata['author_name']}")
    header_lines.append(f"URL: https://www.youtube.com/watch?v={video_id}")
    header = "\n".join(header_lines)
    extracted = f"{header}\n\n{transcript_text}".strip() if transcript_text else header

    _write_text(archive_dir / "extracted.txt", extracted)
    _write_json(archive_dir / "metadata.json", metadata)
    return FetchResult(
        source_url=source_url,
        resolved_url=f"https://www.youtube.com/watch?v={video_id}",
        source_kind="youtube",
        title=title or _title_from_url(source_url) or video_id,
        summary=summary,
        extracted_text=extracted,
        local_archive=str(archive_dir),
        pdf_path=None,
        content_hash=content_hash(extracted),
        fetch_status="fetched",
        fetch_error=None,
        fetched_at=fetched_at,
        metadata=metadata,
    )


def _youtube_transcript(video_id: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi

    segments = YouTubeTranscriptApi.get_transcript(video_id)
    parts = [str(segment.get("text", "")).strip() for segment in segments]
    return re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip()


def _hf_kind(url: str) -> tuple[str, str] | None:
    """Return (kind, repo_or_id) for a Hugging Face URL, else None.

    kind is one of 'paper', 'dataset', 'model'.
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"huggingface.co", "www.huggingface.co"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    if parts[0] == "papers" and len(parts) >= 2:
        return "paper", parts[1]
    if parts[0] == "datasets" and len(parts) >= 2:
        return "dataset", "/".join(parts[1:3])
    reserved = {"models", "spaces", "organizations", "settings", "docs", "blog", "join", "login", "pricing"}
    if parts[0] in reserved:
        return None
    if len(parts) >= 2:
        return "model", "/".join(parts[:2])
    return None


def _fetch_huggingface(source_url: str, archive_dir: Path, fetched_at: str) -> FetchResult:
    parsed = _hf_kind(source_url)
    if not parsed:
        raise ValueError("Hugging Face URL is not a model, dataset, or paper URL")
    kind, repo = parsed

    if kind == "paper":
        arxiv_url = f"https://arxiv.org/abs/{repo}"
        return _fetch_arxiv(arxiv_url, archive_dir, fetched_at)

    api_segment = "datasets" if kind == "dataset" else "models"
    repo_meta = _fetch_huggingface_metadata(api_segment, repo)

    raw_prefix = f"datasets/{repo}" if kind == "dataset" else repo
    readme_url = f"https://huggingface.co/{raw_prefix}/raw/main/README.md"
    readme_text = ""
    try:
        readme_bytes, _, _ = _http_get_bytes(readme_url)
        readme_text = readme_bytes.decode("utf-8", errors="replace")
        _write_text(archive_dir / "readme.md", readme_text)
    except Exception as exc:
        repo_meta["readme_error"] = f"{type(exc).__name__}: {exc}"[:500]

    header = _huggingface_metadata_header(kind, repo, repo_meta)
    extracted_text = f"{header}\n\n{readme_text}".strip() if readme_text else header

    html_url = f"https://huggingface.co/{raw_prefix}"
    metadata = {
        "source_url": source_url,
        "resolved_url": html_url,
        "hf_kind": kind,
        "repo": repo,
        **{f"hf_{k}": v for k, v in repo_meta.items()},
    }
    _write_text(archive_dir / "extracted.txt", extracted_text)
    _write_json(archive_dir / "metadata.json", metadata)
    return FetchResult(
        source_url=source_url,
        resolved_url=html_url,
        source_kind="huggingface",
        title=repo,
        summary=repo_meta.get("description") or (f"Hugging Face {kind}: {repo}"),
        extracted_text=extracted_text,
        local_archive=str(archive_dir),
        pdf_path=None,
        content_hash=content_hash(extracted_text),
        fetch_status="fetched",
        fetch_error=None,
        fetched_at=fetched_at,
        metadata=metadata,
    )


def _fetch_huggingface_metadata(api_segment: str, repo: str) -> dict[str, Any]:
    try:
        api_url = f"https://huggingface.co/api/{api_segment}/{repo}"
        data_bytes, _, _ = _http_get_bytes(api_url)
        data = json.loads(data_bytes.decode("utf-8"))
        result: dict[str, Any] = {}
        if isinstance(data.get("downloads"), int):
            result["downloads"] = data["downloads"]
        if isinstance(data.get("likes"), int):
            result["likes"] = data["likes"]
        if isinstance(data.get("pipeline_tag"), str) and data["pipeline_tag"]:
            result["pipeline_tag"] = data["pipeline_tag"]
        if isinstance(data.get("lastModified"), str):
            result["last_modified"] = data["lastModified"][:10]
        if isinstance(data.get("tags"), list):
            result["tags"] = [t for t in data["tags"] if isinstance(t, str)][:20]
        card = data.get("cardData") if isinstance(data.get("cardData"), dict) else {}
        if isinstance(card.get("license"), str):
            result["license"] = card["license"]
        return result
    except Exception:
        return {}


def _huggingface_metadata_header(kind: str, repo: str, meta: dict[str, Any]) -> str:
    lines = [f"Hugging Face {kind}: {repo}"]
    if meta.get("pipeline_tag"):
        lines.append(f"Task: {meta['pipeline_tag']}")
    if meta.get("downloads") is not None:
        lines.append(f"Downloads: {meta['downloads']}")
    if meta.get("likes") is not None:
        lines.append(f"Likes: {meta['likes']}")
    if meta.get("license"):
        lines.append(f"License: {meta['license']}")
    if meta.get("last_modified"):
        lines.append(f"Last modified: {meta['last_modified']}")
    if meta.get("tags"):
        lines.append(f"Tags: {', '.join(meta['tags'])}")
    return "\n".join(lines)


def _fetch_website(source_url: str, archive_dir: Path, fetched_at: str) -> FetchResult:
    try:
        html_bytes, resolved_url, content_type = _http_get_bytes(source_url)
    except FetchBlockedError as blocked:
        if _use_jina_reader_fallback():
            return _fetch_website_via_jina(source_url, archive_dir, fetched_at, blocked)
        raise
    if content_type and "application/pdf" in content_type.lower():
        pdf_path = archive_dir / "source.pdf"
        pdf_path.write_bytes(html_bytes)
        extracted_pdf, pdf_meta = _extract_pdf(html_bytes)
        url_title = _title_from_url(resolved_url)
        pdf_title = _clean_pdf_title(pdf_meta.get("title"), url_title)
        pdf_metadata = {
            "source_url": source_url,
            "resolved_url": resolved_url,
            "content_type": content_type,
            "title_source": "pdf_meta" if pdf_title else "url",
            **_pdf_metadata_fields(pdf_meta),
        }
        _write_text(archive_dir / "extracted.txt", extracted_pdf)
        _write_json(archive_dir / "metadata.json", pdf_metadata)
        return FetchResult(
            source_url=source_url,
            resolved_url=resolved_url,
            source_kind="pdf",
            title=pdf_title or url_title,
            summary=None,
            extracted_text=extracted_pdf,
            local_archive=str(archive_dir),
            pdf_path=str(pdf_path),
            content_hash=content_hash(extracted_pdf, fallback_bytes=html_bytes),
            fetch_status="fetched",
            fetch_error=None,
            fetched_at=fetched_at,
            metadata=pdf_metadata,
        )

    html = html_bytes.decode(_guess_encoding(content_type), errors="replace")
    _write_text(archive_dir / "raw.html", html)

    title, extracted, metadata = extract_website_text(html, resolved_url, archive_dir)
    metadata.update({
        "source_url": source_url,
        "resolved_url": resolved_url,
        "content_type": content_type,
        "title_source": "html" if title else "url",
    })
    title = title or _title_from_url(resolved_url)
    _write_text(archive_dir / "extracted.txt", extracted)
    _write_json(archive_dir / "metadata.json", metadata)
    return FetchResult(
        source_url=source_url,
        resolved_url=resolved_url,
        source_kind="website",
        title=title,
        summary=metadata.get("description"),
        extracted_text=extracted,
        local_archive=str(archive_dir),
        pdf_path=None,
        content_hash=content_hash(extracted, fallback_bytes=html_bytes),
        fetch_status="fetched",
        fetch_error=None,
        fetched_at=fetched_at,
        metadata=metadata,
    )


def _use_jina_reader_fallback() -> bool:
    return load_fetch_settings().use_jina_reader


def _fetch_website_via_jina(
    source_url: str, archive_dir: Path, fetched_at: str, blocked: FetchBlockedError
) -> FetchResult:
    # The origin hard-blocked us; ask the r.jina.ai reader proxy to fetch and
    # extract the page server-side. If that also fails, surface the original block.
    try:
        raw, _resolved, _content_type = _http_get_bytes(JINA_READER_PREFIX + source_url)
        extracted = _normalize_extracted_text(raw.decode("utf-8", errors="replace"))
    except Exception:
        raise blocked
    if not extracted.strip():
        raise blocked
    metadata = {
        "source_url": source_url,
        "resolved_url": source_url,
        "fetch_via": "jina",
        "blocked_status": blocked.status_code,
    }
    _write_text(archive_dir / "extracted.txt", extracted)
    _write_json(archive_dir / "metadata.json", metadata)
    LOGGER.info("Recovered %s via r.jina.ai after HTTP %d block", source_url, blocked.status_code)
    return FetchResult(
        source_url=source_url,
        resolved_url=source_url,
        source_kind="website",
        title=_title_from_url(source_url),
        summary=None,
        extracted_text=extracted,
        local_archive=str(archive_dir),
        pdf_path=None,
        content_hash=content_hash(extracted),
        fetch_status="fetched",
        fetch_error=None,
        fetched_at=fetched_at,
        metadata=metadata,
    )


def _http_get_bytes(url: str, headers: dict[str, str] | None = None) -> tuple[bytes, str, str | None]:
    import httpx

    settings = load_fetch_settings()
    request_headers = dict(BROWSER_HEADERS)
    if headers:
        request_headers.update(headers)
    timeout = httpx.Timeout(settings.timeout_seconds)
    retryable = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.PoolTimeout,
    )
    start_url = _validate_fetch_url(url)
    last_exc: Exception | None = None
    for attempt in range(settings.retry_attempts):
        current_url = start_url
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, headers=request_headers) as client:
                for _redirect in range(settings.max_redirects + 1):
                    current_url = _validate_fetch_url(current_url)
                    with client.stream("GET", current_url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            response.read()
                            location = response.headers.get("location")
                            if not location:
                                response.raise_for_status()
                            current_url = _validate_fetch_url(urljoin(str(response.url), location))
                            continue
                        if response.status_code in _BLOCKED_STATUSES:
                            # Drain so the connection can close cleanly, then surface a clear block.
                            response.read()
                            raise FetchBlockedError(response.status_code, str(response.url))
                        response.raise_for_status()
                        chunks: list[bytes] = []
                        total = 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > settings.max_download_bytes:
                                raise ValueError(f"Response exceeded {settings.max_download_bytes} byte limit")
                            chunks.append(chunk)
                        content_type = response.headers.get("content-type")
                        return b"".join(chunks), str(response.url), content_type
                raise ValueError(f"Too many redirects while fetching {url}")
        except httpx.HTTPStatusError as exc:
            # Retry transient server errors and rate limits; other 4xx propagate.
            status = exc.response.status_code
            if (status >= 500 or status == 429) and attempt < settings.retry_attempts - 1:
                last_exc = exc
            else:
                raise
        except retryable as exc:
            if attempt == settings.retry_attempts - 1:
                raise
            last_exc = exc
        LOGGER.warning(
            "Fetch failed for %s (%s); retry %d/%d",
            url,
            type(last_exc).__name__,
            attempt + 1,
            settings.retry_attempts - 1,
        )
        time.sleep(settings.retry_backoff_base * (2 ** attempt))
    raise last_exc  # pragma: no cover - loop either returns or raises


def _validate_fetch_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http:// and https:// URLs can be fetched")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("Fetch URL must include a host")
    if _allow_private_fetches():
        return url
    _reject_private_host(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    return url


def _allow_private_fetches() -> bool:
    return load_fetch_settings().allow_private


def _reject_private_host(host: str, port: int) -> None:
    try:
        addresses = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError(f"Could not resolve fetch host: {host}") from exc
        addresses = []
        for info in infos:
            sockaddr = info[4]
            if not sockaddr:
                continue
            try:
                addresses.append(ipaddress.ip_address(str(sockaddr[0])))
            except ValueError:
                continue
    if not addresses:
        raise ValueError(f"Could not resolve fetch host: {host}")
    blocked = [addr for addr in addresses if _blocked_ip(addr)]
    if blocked:
        raise ValueError(f"Refusing to fetch private or local address for host: {host}")


def _blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _extract_pdf(pdf_bytes: bytes) -> tuple[str, dict[str, Any]]:
    """Return (extracted text, document metadata) from a PDF in a single parse."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to extract PDF text") from exc

    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        text = "\n\n".join(page.get_text("text").strip() for page in document if page.get_text("text").strip())
        metadata = dict(document.metadata or {})
    return text, metadata


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    return _extract_pdf(pdf_bytes)[0]


# PDF /Title fields are frequently authoring-tool junk rather than the real document title.
_PDF_TITLE_JUNK_RE = re.compile(
    r"^(microsoft word|microsoft powerpoint|powerpoint presentation|untitled|slide\s*\d*|presentation\d*|document\d*|print|paper|main|temp)\b",
    re.IGNORECASE,
)


def _norm_title_key(value: str) -> str:
    return re.sub(r"[\s\-_]+", "", value).lower()


def _clean_pdf_title(raw: str | None, fallback_title: str | None = None) -> str | None:
    """Return a trustworthy PDF /Title, or None when it looks like junk.

    Rejects authoring-tool defaults, file-name-like values, and anything that just
    reproduces the URL/filename stem we'd otherwise derive.
    """
    if not raw or not isinstance(raw, str):
        return None
    title = re.sub(r"\s+", " ", raw).strip()
    if len(title) < 4:
        return None
    if _PDF_TITLE_JUNK_RE.match(title):
        return None
    if title.lower().endswith((".pdf", ".doc", ".docx", ".tex")):
        return None
    if fallback_title and _norm_title_key(title) == _norm_title_key(fallback_title):
        return None
    return title


def _pdf_metadata_fields(meta: dict[str, Any]) -> dict[str, Any]:
    """A curated subset of PDF document metadata worth surfacing (Phase 7)."""
    fields: dict[str, Any] = {}
    for src, dst in (("author", "pdf_author"), ("subject", "pdf_subject"), ("keywords", "pdf_keywords"), ("creationDate", "pdf_created")):
        value = meta.get(src)
        if isinstance(value, str):
            value = value.strip()
        if value:
            fields[dst] = value
    return fields


def _extract_html(html: str, resolved_url: str) -> tuple[str | None, str, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    extracted = ""
    try:
        import trafilatura
        from trafilatura.metadata import extract_metadata

        extracted = trafilatura.extract(html, url=resolved_url, include_comments=False, include_tables=True) or ""
        trafilatura_metadata = extract_metadata(html, default_url=resolved_url)
        if trafilatura_metadata is not None:
            metadata = _clean_metadata(trafilatura_metadata.as_dict())
    except Exception as exc:
        metadata["trafilatura_error"] = f"{type(exc).__name__}: {exc}"

    fallback = _SimpleHTMLTextExtractor()
    fallback.feed(html)
    title = metadata.get("title") or fallback.title
    if not extracted.strip():
        extracted = fallback.text
    if fallback.description and "description" not in metadata:
        metadata["description"] = fallback.description
    return title, _normalize_extracted_text(extracted), metadata


def _clean_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        item = _clean_metadata_value(value)
        if item is not None:
            cleaned[key] = item
    return cleaned


def _clean_metadata_value(value: object) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        items = [_clean_metadata_value(item) for item in value]
        items = [item for item in items if item is not None]
        return items or None
    if isinstance(value, dict):
        data = {str(k): _clean_metadata_value(v) for k, v in value.items()}
        data = {k: v for k, v in data.items() if v is not None}
        return data or None
    return None


def _normalize_extracted_text(text: str) -> str:
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text.strip())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def extract_website_text(html: str, resolved_url: str, archive_dir: Path | None = None) -> tuple[str | None, str, dict[str, Any]]:
    title, extracted, metadata = _extract_html(html, resolved_url)
    if _has_enough_text(extracted):
        return title, extracted, metadata

    embedded = _extract_embedded_html(html, resolved_url, archive_dir)
    if embedded is None:
        if metadata.get("description") and not extracted.strip():
            metadata["extraction_fallback"] = "metadata_description"
            return title, metadata["description"], metadata
        return title, extracted, metadata

    embedded_title, embedded_text, embedded_metadata = embedded
    merged_metadata = {**metadata, **{f"embedded_{key}": value for key, value in embedded_metadata.items()}}
    merged_metadata["extraction_fallback"] = "embedded_html"
    return title or embedded_title, embedded_text, merged_metadata


def _has_enough_text(text: str) -> bool:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", text)
    return len(words) >= 40


def _extract_embedded_html(html: str, resolved_url: str, archive_dir: Path | None) -> tuple[str | None, str, dict[str, Any]] | None:
    candidates: list[tuple[str, str]] = []
    for index, iframe_src in enumerate(_iframe_sources(html), start=1):
        iframe_url = urljoin(resolved_url, iframe_src)
        if not _same_site(resolved_url, iframe_url):
            continue
        candidates.append((f"embedded-{index}.html", iframe_url))
    best: tuple[str | None, str, dict[str, Any]] | None = None
    best_word_count = 0
    seen: set[str] = set()
    queue = candidates[:3]
    processed = 0
    while queue and processed < 6:
        archive_name, candidate_url = queue.pop(0)
        if candidate_url in seen:
            continue
        seen.add(candidate_url)
        processed += 1
        try:
            payload, fetched_url, content_type = _http_get_bytes(candidate_url)
        except Exception:
            continue
        if content_type and "html" not in content_type.lower():
            continue
        candidate_html = payload.decode(_guess_encoding(content_type), errors="replace")
        if archive_dir is not None:
            _write_text(archive_dir / archive_name, candidate_html)

        target = parse_qs(urlparse(fetched_url).query).get("target", [None])[0]
        if target and "targetFolder" in candidate_html and "/main.html" in candidate_html:
            main_url = urljoin(fetched_url, f"../{target}/main.html")
            queue.append((archive_name.replace(".html", "-main.html"), main_url))

        candidate_title, candidate_text, candidate_metadata = _extract_html(candidate_html, fetched_url)
        word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", candidate_text))
        score = word_count + (100000 if urlparse(fetched_url).path.endswith("/main.html") else 0)
        if score > best_word_count:
            candidate_metadata = dict(candidate_metadata)
            candidate_metadata["embedded_url"] = fetched_url
            best = candidate_title, candidate_text, candidate_metadata
            best_word_count = score

    if best and _has_enough_text(best[1]):
        return best
    return None


def _iframe_sources(html: str) -> list[str]:
    parser = _IframeSourceExtractor()
    parser.feed(html)
    return parser.sources


def extract_read_more_links(html: str, base_url: str) -> list[str]:
    """Return the targets of "Read more"-style anchors in a digest/newsletter post.

    Roundup posts label each item with a `<a ...>Read more</a>` link pointing at the
    underlying repo / project page / paper; those are the substantive links worth
    saving (the post itself is not). Deduped, resolved against base_url, http(s) only.
    """
    parser = _ReadMoreLinkExtractor()
    parser.feed(html)
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        url = urljoin(base_url, href)
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _is_read_more(text: str) -> bool:
    return text.strip().lower().lstrip("→▸»·- ").startswith("read more")


def _same_site(base_url: str, candidate_url: str) -> bool:
    base = urlparse(base_url)
    candidate = urlparse(candidate_url)
    return candidate.scheme in {"http", "https"} and candidate.netloc == base.netloc



def _parse_arxiv_atom(data: bytes) -> dict[str, Any]:
    root = ElementTree.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError("arXiv API returned no entry")

    def text(name: str) -> str | None:
        child = entry.find(f"atom:{name}", ns)
        if child is None or child.text is None:
            return None
        return re.sub(r"\s+", " ", child.text).strip()

    authors = []
    for author in entry.findall("atom:author", ns):
        name = author.find("atom:name", ns)
        if name is not None and name.text:
            authors.append(name.text.strip())
    return {
        "title": text("title"),
        "summary": text("summary"),
        "published": text("published"),
        "updated": text("updated"),
        "authors": authors,
    }


def _github_owner_repo(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    if len(parts) > 2 and parts[2] in {"blob", "tree", "pull", "issues", "commit", "releases"}:
        return None
    return parts[0], parts[1].removesuffix(".git")


def content_hash(text: str, fallback_bytes: bytes | None = None) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip().encode("utf-8")
    payload = normalized or fallback_bytes or b""
    if not payload:
        return None
    return hashlib.sha256(payload).hexdigest()


def _guess_encoding(content_type: str | None) -> str:
    if content_type:
        match = re.search(r"charset=([^;]+)", content_type, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "utf-8"


def _title_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    stem = Path(parsed.path).stem
    return re.sub(r"[-_]+", " ", stem).strip() or parsed.netloc or None


def _title_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    return re.sub(r"[-_]+", " ", stem).strip() or filename or None


def slugify_filename(filename: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")
    return slug[:120] or "upload"


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


class _IframeSourceExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "iframe":
            return
        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        src = attr_map.get("src")
        if src:
            self.sources.append(src)


class _ReadMoreLinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attr_map = {key.lower(): value for key, value in attrs if value is not None}
            self._href = attr_map.get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
            if _is_read_more(text):
                self.links.append(self._href)
            self._href = None
            self._parts = []


class _SimpleHTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.description: str | None = None
        self._in_title = False
        self._skip_depth = 0
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._text_parts)).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attr_map = {key.lower(): value for key, value in attrs if value is not None}
            if attr_map.get("name", "").lower() == "description" or attr_map.get("property", "").lower() == "og:description":
                self.description = attr_map.get("content")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
            self.title = re.sub(r"\s+", " ", " ".join(self._title_parts)).strip() or None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if not stripped:
            return
        if self._in_title:
            self._title_parts.append(stripped)
        else:
            self._text_parts.append(stripped)

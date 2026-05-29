from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from xml.etree import ElementTree

USER_AGENT = "PRISM/0.2 (+https://github.com/local/prism)"
FETCH_TIMEOUT_SECONDS = 45.0
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


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
    if host == "github.com" and _github_owner_repo(url):
        return "github"
    if parsed.scheme in {"http", "https"}:
        return "website"
    return "unknown"


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
    pdf_text = _extract_pdf_text(pdf_bytes)
    extracted = "\n\n".join(part for part in [entry.get("summary"), pdf_text] if part).strip()

    metadata = {
        "source_url": source_url,
        "metadata_url": metadata_resolved,
        "metadata_error": metadata_error,
        "pdf_url": pdf_resolved,
        "content_type": pdf_content_type,
        "arxiv_id": arxiv_id,
        **entry,
    }
    _write_text(archive_dir / "extracted.txt", extracted)
    _write_json(archive_dir / "metadata.json", metadata)
    return FetchResult(
        source_url=source_url,
        resolved_url=pdf_resolved,
        source_kind="paper",
        title=entry.get("title") or _title_from_url(pdf_resolved),
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
    extracted = _extract_pdf_text(pdf_bytes)
    title = _title_from_url(resolved_url)
    metadata = {"source_url": source_url, "resolved_url": resolved_url, "content_type": content_type}
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


def _fetch_website(source_url: str, archive_dir: Path, fetched_at: str) -> FetchResult:
    html_bytes, resolved_url, content_type = _http_get_bytes(source_url)
    if content_type and "application/pdf" in content_type.lower():
        pdf_path = archive_dir / "source.pdf"
        pdf_path.write_bytes(html_bytes)
        extracted_pdf = _extract_pdf_text(html_bytes)
        pdf_metadata = {"source_url": source_url, "resolved_url": resolved_url, "content_type": content_type}
        _write_text(archive_dir / "extracted.txt", extracted_pdf)
        _write_json(archive_dir / "metadata.json", pdf_metadata)
        return FetchResult(
            source_url=source_url,
            resolved_url=resolved_url,
            source_kind="pdf",
            title=_title_from_url(resolved_url),
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
    metadata.update({"source_url": source_url, "resolved_url": resolved_url, "content_type": content_type})
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


def _http_get_bytes(url: str, headers: dict[str, str] | None = None) -> tuple[bytes, str, str | None]:
    import httpx

    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS)
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=request_headers) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"Response exceeded {MAX_DOWNLOAD_BYTES} byte limit")
                chunks.append(chunk)
            content_type = response.headers.get("content-type")
            return b"".join(chunks), str(response.url), content_type


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to extract PDF text") from exc

    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        return "\n\n".join(page.get_text("text").strip() for page in document if page.get_text("text").strip())


def _extract_html(html: str, resolved_url: str) -> tuple[str | None, str, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    extracted = ""
    try:
        import trafilatura
        from trafilatura.metadata import extract_metadata

        extracted = trafilatura.extract(html, url=resolved_url, include_comments=False, include_tables=True) or ""
        trafilatura_metadata = extract_metadata(html, default_url=resolved_url)
        if trafilatura_metadata:
            metadata = {key: value for key, value in trafilatura_metadata.as_dict().items() if value}
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

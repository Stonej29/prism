"""Extract representative images from a saved source's archive.

One reusable entry point — `extract_images_for_archive` — used both at fetch time
(via `fetch._attach_images`) and for backfilling existing notes
(`NoteService.extract_images`). It reads whatever the fetch pipeline already
archived (`source.pdf` / `raw.html` / `readme.md` / YouTube `video_id`), pulls a
bounded set of images, downscales them with PyMuPDF (no Pillow), and writes JPEGs
to `<archive>/images/`. Everything is best-effort: any failure yields fewer (or
no) images, never an exception that breaks a save.
"""
from __future__ import annotations

import logging
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

LOGGER = logging.getLogger(__name__)

IMAGE_MAX_DIM = 1280       # longest side after downscaling
IMAGE_MAX_COUNT = 12       # cap stored images per note
IMAGE_MIN_DIM = 200        # skip icons / badges / tracking pixels
IMAGE_JPEG_QUALITY = 80
_MAX_IMAGE_BYTES = 6 * 1024 * 1024

# Hosts / url fragments that serve status badges or icons rather than content.
_BADGE_MARKERS = ("shields.io", "badgen.net", "badge.fury.io", "codecov.io",
                  "coveralls.io", "travis-ci", "circleci.com", "/badge", "badge.svg")


def extraction_enabled() -> bool:
    """Fetch-time auto-extraction gate (backfill ignores this and always runs)."""
    return os.getenv("PRISM_IMAGE_EXTRACTION", "1").strip().lower() not in {"0", "false", "no"}


def extract_images_for_archive(archive_dir: Path | str, source_kind: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract, downscale, and store images for one note's archive.

    Returns a list of ``{"file": "img-001.jpg", "w": W, "h": H}`` (relative to
    ``<archive>/images/``). Never raises.
    """
    archive_dir = Path(archive_dir)
    raw: list[bytes] = []
    try:
        pdf = archive_dir / "source.pdf"
        html = archive_dir / "raw.html"
        readme = archive_dir / "readme.md"
        if pdf.is_file():
            raw = _collect_pdf_images(pdf)
        elif source_kind == "youtube" and metadata.get("video_id"):
            thumb = _download_youtube_thumbnail(str(metadata["video_id"]))
            raw = [thumb] if thumb else []
        elif html.is_file():
            base = str(metadata.get("resolved_url") or metadata.get("source_url") or "")
            raw = _download_many(_web_image_urls(html.read_text(encoding="utf-8", errors="ignore"), base, metadata))
        elif readme.is_file():
            raw = _download_many(_readme_image_urls(readme.read_text(encoding="utf-8", errors="ignore")))
    except Exception as exc:  # noqa: BLE001 - non-blocking by design
        LOGGER.warning("Image source read failed for %s: %s", archive_dir, exc)
        return []

    images_dir = archive_dir / "images"
    _clear_images(images_dir)
    out: list[dict[str, Any]] = []
    for data in raw:
        if len(out) >= IMAGE_MAX_COUNT:
            break
        result = _downscale_to_jpeg(data)
        if not result:
            continue
        jpeg, width, height = result
        name = f"img-{len(out) + 1:03d}.jpg"
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / name).write_bytes(jpeg)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to write image %s: %s", name, exc)
            continue
        out.append({"file": name, "w": width, "h": height})
    return out


def _clear_images(images_dir: Path) -> None:
    """Drop previously-extracted JPEGs so re-runs (backfill) stay idempotent."""
    if not images_dir.is_dir():
        return
    for old in images_dir.glob("img-*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass


def _downscale_to_jpeg(data: bytes) -> tuple[bytes, int, int] | None:
    """Load image bytes, drop tiny ones, convert to RGB, downscale, return JPEG.

    Pillow is the primary decoder because it covers the formats the modern web
    actually serves — WebP, AVIF (where libavif is present), PNG, JPEG, GIF —
    which PyMuPDF's Pixmap cannot read (it fails on WebP/AVIF). PyMuPDF is kept
    only as a fallback so extraction still degrades gracefully if Pillow is
    somehow unavailable.
    """
    result = _downscale_with_pillow(data)
    if result is not None:
        return result
    return _downscale_with_fitz(data)


def _downscale_with_pillow(data: bytes) -> tuple[bytes, int, int] | None:
    try:
        import io

        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard dep
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001 - unsupported/corrupt image
        return None
    width, height = img.size
    if width < IMAGE_MIN_DIM or height < IMAGE_MIN_DIM:
        return None
    if img.mode != "RGB":  # JPEG can't carry alpha / palette / CMYK
        try:
            img = img.convert("RGB")
        except Exception:  # noqa: BLE001
            return None
    longest = max(width, height)
    if longest > IMAGE_MAX_DIM:
        scale = IMAGE_MAX_DIM / longest
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        try:
            img = img.resize(size, Image.LANCZOS)
        except Exception:  # noqa: BLE001
            pass
    try:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=IMAGE_JPEG_QUALITY)
    except Exception:  # noqa: BLE001
        return None
    return buf.getvalue(), img.width, img.height


def _downscale_with_fitz(data: bytes) -> tuple[bytes, int, int] | None:
    try:
        import fitz
    except ImportError:  # pragma: no cover
        return None
    try:
        pix = fitz.Pixmap(data)
    except Exception:  # noqa: BLE001 - unsupported/corrupt image (e.g. WebP)
        return None
    if pix.width < IMAGE_MIN_DIM or pix.height < IMAGE_MIN_DIM:
        return None
    if pix.alpha or pix.colorspace is None or pix.colorspace.n not in (1, 3):
        try:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        except Exception:  # noqa: BLE001
            return None
    longest = max(pix.width, pix.height)
    halvings = 0
    while longest / (2 ** halvings) > IMAGE_MAX_DIM:
        halvings += 1
    if halvings:
        try:
            pix.shrink(halvings)  # divides both sides by 2**halvings, in place
        except Exception:  # noqa: BLE001
            pass
    try:
        jpeg = pix.tobytes(output="jpeg", jpg_quality=IMAGE_JPEG_QUALITY)
    except Exception:  # noqa: BLE001
        return None
    return jpeg, pix.width, pix.height


def _collect_pdf_images(pdf_path: Path) -> list[bytes]:
    """Embedded images across all pages, deduped by xref, tiny ones pre-skipped."""
    try:
        import fitz
    except ImportError:  # pragma: no cover
        return []
    out: list[bytes] = []
    seen: set[int] = set()
    with fitz.open(pdf_path) as doc:
        for page in doc:
            for info in page.get_images(full=True):
                xref = info[0]
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    img = doc.extract_image(xref)
                except Exception:  # noqa: BLE001
                    continue
                if not img or not img.get("image"):
                    continue
                if img.get("width", 0) < IMAGE_MIN_DIM or img.get("height", 0) < IMAGE_MIN_DIM:
                    continue
                out.append(img["image"])
                if len(out) >= IMAGE_MAX_COUNT * 3:  # gather extra; downscale filters more
                    return out
    return out


class _ImgSrcExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        attr = {k.lower(): v for k, v in attrs if v}
        src = attr.get("src") or attr.get("data-src")
        if not src and attr.get("srcset"):
            src = attr["srcset"].split(",")[0].strip().split(" ")[0]
        if src:
            self.srcs.append(src)


def _is_badge(url: str) -> bool:
    low = url.lower()
    return any(marker in low for marker in _BADGE_MARKERS)


def _web_image_urls(html: str, base_url: str, metadata: dict[str, Any]) -> list[str]:
    parser = _ImgSrcExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        pass
    candidates: list[str] = []
    hero = metadata.get("og_image") or metadata.get("image")
    if isinstance(hero, str):
        candidates.append(hero)
    candidates.extend(parser.srcs)
    return _filter_urls(candidates, base_url)


def _readme_image_urls(readme: str) -> list[str]:
    # README markdown ![alt](url) plus any inline <img>. Only absolute URLs are
    # kept — relative repo paths can't be resolved reliably without the branch.
    urls = re.findall(r"!\[[^\]]*\]\(\s*(\S+?)[\s)]", readme)
    parser = _ImgSrcExtractor()
    try:
        parser.feed(readme)
    except Exception:  # noqa: BLE001
        pass
    urls.extend(parser.srcs)
    return _filter_urls(urls, base_url="")


def _filter_urls(candidates: list[str], base_url: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        if not raw:
            continue
        url = urljoin(base_url, raw) if base_url else raw
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        low = url.lower()
        if low.endswith(".svg") or _is_badge(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= IMAGE_MAX_COUNT * 2:
            break
    return out


def _download_many(urls: list[str]) -> list[bytes]:
    out: list[bytes] = []
    for url in urls:
        if len(out) >= IMAGE_MAX_COUNT * 2:
            break
        data = _download_image(url)
        if data:
            out.append(data)
    return out


def _download_image(url: str) -> bytes | None:
    # Reuse the hardened fetcher (SSRF guards, size cap, redirects). Lazy import
    # avoids a circular dependency with fetch.py.
    from prism.fetch import _http_get_bytes

    try:
        data, _resolved, content_type = _http_get_bytes(url, headers={"Accept": "image/*"})
    except Exception:  # noqa: BLE001 - bad/blocked image url is fine to skip
        return None
    if content_type and "image" not in content_type.lower():
        return None
    if len(data) > _MAX_IMAGE_BYTES:
        return None
    return data


def _download_youtube_thumbnail(video_id: str) -> bytes | None:
    from prism.fetch import _http_get_bytes

    for quality in ("maxresdefault", "hqdefault"):
        url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
        try:
            data, _resolved, content_type = _http_get_bytes(url)
        except Exception:  # noqa: BLE001
            continue
        if data and (not content_type or "image" in content_type.lower()):
            return data
    return None

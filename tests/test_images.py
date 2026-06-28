import tempfile
import unittest
from pathlib import Path

import fitz

from prism import images


def _png(width: int, height: int, gray: int = 200) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.clear_with(gray)
    return pix.tobytes("png")


def _webp(width: int, height: int) -> bytes:
    """A real WebP — the format modern sites (WordPress/CDN) serve that PyMuPDF can't decode."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (180, 120, 90)).save(buf, format="WEBP")
    return buf.getvalue()


def _pdf_with_image(image_png: bytes) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(0, 0, 320, 320), stream=image_png)
    data = doc.tobytes()
    doc.close()
    return data


class ImageExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.archive = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pdf_images_extracted_and_downscaled(self) -> None:
        (self.archive / "source.pdf").write_bytes(_pdf_with_image(_png(2000, 1000)))
        result = images.extract_images_for_archive(self.archive, "pdf", {})
        self.assertEqual(len(result), 1)
        entry = result[0]
        # Stored file exists and is downscaled to <= MAX_DIM on the long side.
        stored = self.archive / "images" / entry["file"]
        self.assertTrue(stored.is_file())
        self.assertLessEqual(max(entry["w"], entry["h"]), images.IMAGE_MAX_DIM)

    def test_tiny_images_skipped(self) -> None:
        (self.archive / "source.pdf").write_bytes(_pdf_with_image(_png(50, 50)))
        self.assertEqual(images.extract_images_for_archive(self.archive, "pdf", {}), [])

    def test_website_images_downloaded(self) -> None:
        (self.archive / "raw.html").write_text(
            '<html><body><img src="https://example.com/a.png">'
            '<img src="https://img.shields.io/badge.svg">'  # badge: filtered
            "</body></html>",
            encoding="utf-8",
        )
        png = _png(400, 300)
        import prism.fetch as fetch

        original = fetch._http_get_bytes
        fetch._http_get_bytes = lambda url, headers=None: (png, url, "image/png")  # type: ignore[assignment]
        try:
            result = images.extract_images_for_archive(
                self.archive, "website", {"resolved_url": "https://example.com/post"}
            )
        finally:
            fetch._http_get_bytes = original  # type: ignore[assignment]
        self.assertEqual(len(result), 1)  # badge skipped, one real image kept

    def test_webp_is_decoded_and_downscaled(self) -> None:
        # Regression: PyMuPDF cannot decode WebP, so a WebP-only page yielded zero
        # images. Pillow decodes it; it should be stored as a downscaled JPEG.
        result = images._downscale_to_jpeg(_webp(2000, 1000))
        self.assertIsNotNone(result)
        jpeg, width, height = result
        self.assertEqual(jpeg[:2], b"\xff\xd8")  # JPEG SOI marker
        self.assertEqual((width, height), (1280, 640))  # capped to MAX_DIM on the long side

    def test_website_webp_images_downloaded(self) -> None:
        (self.archive / "raw.html").write_text(
            '<html><body><img src="https://example.com/hero.webp"></body></html>',
            encoding="utf-8",
        )
        webp = _webp(800, 600)
        import prism.fetch as fetch

        original = fetch._http_get_bytes
        fetch._http_get_bytes = lambda url, headers=None: (webp, url, "image/webp")  # type: ignore[assignment]
        try:
            result = images.extract_images_for_archive(
                self.archive, "website", {"resolved_url": "https://example.com/post"}
            )
        finally:
            fetch._http_get_bytes = original  # type: ignore[assignment]
        self.assertEqual(len(result), 1)

    def test_missing_source_returns_empty(self) -> None:
        self.assertEqual(images.extract_images_for_archive(self.archive, "website", {}), [])

    def test_rerun_is_idempotent(self) -> None:
        (self.archive / "source.pdf").write_bytes(_pdf_with_image(_png(600, 400)))
        first = images.extract_images_for_archive(self.archive, "pdf", {})
        second = images.extract_images_for_archive(self.archive, "pdf", {})
        self.assertEqual(len(first), len(second))
        # No stale accumulation beyond what the latest run produced.
        stored = list((self.archive / "images").glob("img-*.jpg"))
        self.assertEqual(len(stored), len(second))


if __name__ == "__main__":
    unittest.main()

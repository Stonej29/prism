from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism.db import NoteRecord, PrismDatabase
from prism.fetch import FetchResult, detect_source_kind, parse_arxiv_id
from prism.notes import NoteService, render_note, slugify


class SourceDetectionTests(unittest.TestCase):
    def test_detects_phase2_source_kinds(self) -> None:
        self.assertEqual(detect_source_kind("https://arxiv.org/abs/1908.04064"), "paper")
        self.assertEqual(parse_arxiv_id("https://arxiv.org/pdf/1908.04064.pdf"), "1908.04064")
        self.assertEqual(parse_arxiv_id("https://arxiv.org/abs/hep-th/9901001"), "hep-th/9901001")
        self.assertEqual(detect_source_kind("https://example.com/paper.pdf"), "pdf")
        self.assertEqual(detect_source_kind("https://github.com/openai/openai-python"), "github")
        self.assertEqual(detect_source_kind("https://example.com/article"), "website")

    def test_slugifies_fetched_titles_for_filenames(self) -> None:
        self.assertEqual(slugify("A Fetched: Title / With Punctuation"), "a-fetched-title-with-punctuation")


class DatabaseMigrationTests(unittest.TestCase):
    def test_migrates_phase1_schema_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "prism.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE notes (
                    note_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL UNIQUE,
                    resolved_url TEXT NOT NULL,
                    note_path TEXT NOT NULL,
                    date_saved TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO notes VALUES (
                    'abc123', 'https://example.com', 'https://example.com', 'notes/example.md',
                    '2026-01-01T00:00:00Z', 'unreviewed', 'Old title', 'Old summary'
                )
                """
            )
            conn.commit()
            conn.close()

            db = PrismDatabase(db_path)
            record = db.find_by_source_url("https://example.com")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.source_kind, "unknown")
            self.assertEqual(record.fetch_status, "not_fetched")

    def test_duplicate_lookup_by_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PrismDatabase(Path(tmp) / "prism.sqlite3")
            record = NoteRecord(
                note_id="abc123",
                source_url="https://a.example",
                resolved_url="https://a.example",
                note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z",
                status="unreviewed",
                title="A",
                summary="Fetched website capture",
                source_kind="website",
                content_hash="hash1",
                fetch_status="fetched",
            )
            db.insert_note(record)
            self.assertEqual(db.find_by_content_hash("hash1"), record)
            self.assertIsNone(db.find_by_content_hash(None))


class FetcherIntegrationTests(unittest.TestCase):
    def test_arxiv_fetch_archives_pdf_text_and_metadata(self) -> None:
        atom = b'<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n  <entry>\n    <title>Arxiv Paper</title>\n    <summary>Abstract text.</summary>\n    <published>2019-08-01T00:00:00Z</published>\n    <updated>2019-08-02T00:00:00Z</updated>\n    <author><name>A. Author</name></author>\n  </entry>\n</feed>'
        def fake_get(url: str, headers=None):
            if "export.arxiv.org" in url:
                return atom, url, "application/atom+xml"
            return b"%PDF", "https://arxiv.org/pdf/1908.04064.pdf", "application/pdf"

        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", side_effect=fake_get), patch("prism.fetch._extract_pdf_text", return_value="PDF text"):
                from prism.fetch import fetch_source
                result = fetch_source("https://arxiv.org/abs/1908.04064", Path(tmp), "abc123")

            self.assertEqual(result.source_kind, "paper")
            self.assertEqual(result.title, "Arxiv Paper")
            self.assertIn("PDF text", result.extracted_text)
            self.assertTrue((Path(tmp) / "abc123" / "source.pdf").exists())
            self.assertTrue((Path(tmp) / "abc123" / "metadata.json").exists())

    def test_pdf_fetch_archives_pdf_and_extracted_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", return_value=(b"%PDF", "https://example.com/a.pdf", "application/pdf")), patch("prism.fetch._extract_pdf_text", return_value="PDF body"):
                from prism.fetch import fetch_source
                result = fetch_source("https://example.com/a.pdf", Path(tmp), "pdf123")

            self.assertEqual(result.source_kind, "pdf")
            self.assertEqual(result.extracted_text, "PDF body")
            self.assertTrue((Path(tmp) / "pdf123" / "source.pdf").exists())
            self.assertTrue((Path(tmp) / "pdf123" / "extracted.txt").exists())

    def test_github_fetch_archives_readme(self) -> None:
        payload = b'{"encoding":"base64","content":"IyBUaXRsZVxuQm9keQ==","name":"README.md","path":"README.md","html_url":"https://github.com/o/r/blob/main/README.md"}'
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", return_value=(payload, "https://api.github.com/repos/o/r/readme", "application/json")):
                from prism.fetch import fetch_source
                result = fetch_source("https://github.com/o/r", Path(tmp), "gh123")

            self.assertEqual(result.source_kind, "github")
            self.assertEqual(result.title, "o/r")
            self.assertIn("# Title", result.extracted_text)
            self.assertTrue((Path(tmp) / "gh123" / "readme.md").exists())

    def test_website_fetch_archives_html_and_fallback_text(self) -> None:
        html = b"<html><head><title>Article</title><meta name='description' content='Desc'></head><body><main>Hello <b>world</b></main></body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", return_value=(html, "https://example.com/article", "text/html; charset=utf-8")):
                from prism.fetch import fetch_source
                result = fetch_source("https://example.com/article", Path(tmp), "web123")

            self.assertEqual(result.source_kind, "website")
            self.assertEqual(result.title, "Article")
            self.assertIn("Hello world", result.extracted_text)
            self.assertTrue((Path(tmp) / "web123" / "raw.html").exists())

    def test_website_fetch_recovers_same_site_iframe_content(self) -> None:
        wrapper = b"""<html><head><title>Wrapper</title><meta name='description' content='Wrapper desc'></head><body><iframe src='../shared/index.html?target=world-simulation'></iframe></body></html>"""
        shell = b"""<html><head><title>Shell</title></head><body><script>const targetFolder = 'world-simulation'; $('#includeHtml').load('../' + targetFolder + '/main.html');</script><div>Navigation noise</div></body></html>"""
        main = b"""<html><head><title>World Simulation - NVIDIA SIL</title></head><body><main><h1>World Simulation</h1><p>We develop simulation-first methodologies that enable intelligent agents to safely learn, plan, and act in rich, physically realistic worlds.</p><p>World modeling, autonomous vehicle agents, and humanoid agents are developed together for robust decision making and control.</p><p>The page describes research focus areas, policy learning, physics-based control, evaluation at scale, controllable generation, temporal consistency, synthetic data, and simulation systems for embodied agents.</p></main></body></html>"""

        def fake_get(url: str, headers=None):
            if url == "https://example.com/labs/sil/world-simulation/":
                return wrapper, url, "text/html"
            if url == "https://example.com/labs/sil/shared/index.html?target=world-simulation":
                return shell, url, "text/html"
            if url == "https://example.com/labs/sil/world-simulation/main.html":
                return main, url, "text/html"
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", side_effect=fake_get):
                from prism.fetch import fetch_source
                result = fetch_source("https://example.com/labs/sil/world-simulation/", Path(tmp), "webifr")

            archive = Path(tmp) / "webifr"
            self.assertIn("simulation-first methodologies", result.extracted_text)
            self.assertIn("humanoid agents", result.extracted_text)
            self.assertEqual(result.metadata.get("extraction_fallback"), "embedded_html")
            self.assertTrue((archive / "embedded-1.html").exists())
            self.assertTrue((archive / "embedded-1-main.html").exists())

    def test_fetch_failure_returns_failed_result_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", side_effect=RuntimeError("timeout")):
                from prism.fetch import fetch_source
                result = fetch_source("https://example.com/article", Path(tmp), "fail12")

            self.assertEqual(result.fetch_status, "failed")
            self.assertEqual(result.fetch_error, "timeout")
            self.assertTrue((Path(tmp) / "fail12" / "metadata.json").exists())


class NoteServiceTests(unittest.TestCase):
    def test_save_url_uses_fetch_metadata_and_renders_archive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives")
            fetch = FetchResult(
                source_url="https://example.com/article",
                resolved_url="https://example.com/final",
                source_kind="website",
                title="Fetched Title",
                summary="Description",
                extracted_text="Extracted article text",
                local_archive=str(root / "archives" / "unused"),
                pdf_path=None,
                content_hash="hash1",
                fetch_status="fetched",
                fetch_error=None,
                fetched_at="2026-01-01T00:00:00Z",
                metadata={"title": "Fetched Title"},
            )
            with patch("prism.notes.fetch_source", return_value=fetch):
                result = service.save_url("https://example.com/article")

            self.assertTrue(result.created)
            self.assertEqual(result.record.title, "Fetched Title")
            note_text = (root / "vault" / result.record.note_path).read_text(encoding="utf-8")
            self.assertIn("source_kind: website", note_text)
            self.assertIn("fetch_status: fetched", note_text)
            self.assertIn("content_hash: hash1", note_text)
            self.assertIn("Extracted article text", note_text)

    def test_duplicate_exact_url_and_content_hash_reuse_existing_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives")

            first_fetch = FetchResult(
                source_url="https://example.com/a",
                resolved_url="https://example.com/a",
                source_kind="website",
                title="First",
                summary=None,
                extracted_text="Same text",
                local_archive=str(root / "archives" / "first"),
                pdf_path=None,
                content_hash="samehash",
                fetch_status="fetched",
                fetch_error=None,
                fetched_at="2026-01-01T00:00:00Z",
                metadata={},
            )
            second_fetch = FetchResult(
                source_url="https://mirror.example/a",
                resolved_url="https://mirror.example/a",
                source_kind="website",
                title="Mirror",
                summary=None,
                extracted_text="Same text",
                local_archive=str(root / "archives" / "second"),
                pdf_path=None,
                content_hash="samehash",
                fetch_status="fetched",
                fetch_error=None,
                fetched_at="2026-01-01T00:00:01Z",
                metadata={},
            )

            with patch("prism.notes.fetch_source", return_value=first_fetch):
                first = service.save_url("https://example.com/a")
            exact = service.save_url("https://example.com/a")
            with patch("prism.notes.fetch_source", return_value=second_fetch):
                content_duplicate = service.save_url("https://mirror.example/a")

            self.assertTrue(first.created)
            self.assertFalse(exact.created)
            self.assertEqual(exact.duplicate_reason, "source_url")
            self.assertFalse(content_duplicate.created)
            self.assertEqual(content_duplicate.duplicate_reason, "content_hash")
            self.assertEqual(content_duplicate.record.note_id, first.record.note_id)

    def test_render_note_includes_failed_fetch_metadata(self) -> None:
        record = NoteRecord(
            note_id="abc123",
            source_url="https://example.com",
            resolved_url="https://example.com",
            note_path="notes/example.md",
            date_saved="2026-01-01T00:00:00Z",
            status="unreviewed",
            title="Example",
            summary="Fetch failed",
            source_kind="website",
            fetch_status="failed",
            fetch_error="timeout",
            fetched_at="2026-01-01T00:00:00Z",
        )
        note = render_note(record)
        self.assertIn("fetch_status: failed", note)
        self.assertIn("fetch_error: timeout", note)
        self.assertIn("No extracted text available.", note)


if __name__ == "__main__":
    unittest.main()

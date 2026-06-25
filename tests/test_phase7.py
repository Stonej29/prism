from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism.db import NoteRecord, PrismDatabase
from prism.embedding import EmbeddingConfig
from prism.fetch import (
    FetchResult,
    detect_source_kind,
    extract_read_more_links,
    fetch_source,
    fetch_upload,
    parse_youtube_id,
    _hf_kind,
)
from prism.index import NoteIndexer
from prism.llm import LLMConfig
from prism.notes import NoteService, render_note


class NewSourceDetectionTests(unittest.TestCase):
    def test_detects_youtube(self) -> None:
        self.assertEqual(detect_source_kind("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "youtube")
        self.assertEqual(detect_source_kind("https://youtu.be/dQw4w9WgXcQ"), "youtube")
        self.assertEqual(detect_source_kind("https://www.youtube.com/shorts/abc123def"), "youtube")
        self.assertEqual(parse_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(parse_youtube_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertIsNone(parse_youtube_id("https://example.com/watch?v=x"))

    def test_detects_huggingface(self) -> None:
        self.assertEqual(detect_source_kind("https://huggingface.co/meta-llama/Llama-3-8B"), "huggingface")
        self.assertEqual(detect_source_kind("https://huggingface.co/datasets/squad"), "huggingface")
        self.assertEqual(detect_source_kind("https://huggingface.co/papers/2106.01345"), "huggingface")
        # Reserved/non-repo paths fall back to website.
        self.assertEqual(detect_source_kind("https://huggingface.co/docs/transformers"), "website")

    def test_hf_kind_splits_shapes(self) -> None:
        self.assertEqual(_hf_kind("https://huggingface.co/meta-llama/Llama-3-8B"), ("model", "meta-llama/Llama-3-8B"))
        self.assertEqual(_hf_kind("https://huggingface.co/datasets/org/name"), ("dataset", "org/name"))
        self.assertEqual(_hf_kind("https://huggingface.co/papers/2106.01345"), ("paper", "2106.01345"))
        self.assertIsNone(_hf_kind("https://huggingface.co/settings"))


class YouTubeFetchTests(unittest.TestCase):
    def test_youtube_fetch_combines_metadata_and_transcript(self) -> None:
        oembed = json.dumps({"title": "Great Talk", "author_name": "DeepMind", "author_url": "https://x"}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", return_value=(oembed, "url", "application/json")), \
                 patch("prism.fetch._youtube_transcript", return_value="hello world transcript"):
                result = fetch_source("https://www.youtube.com/watch?v=dQw4w9WgXcQ", Path(tmp), "yt1")
            self.assertEqual(result.source_kind, "youtube")
            self.assertEqual(result.title, "Great Talk")
            self.assertIn("Channel: DeepMind", result.extracted_text)
            self.assertIn("hello world transcript", result.extracted_text)
            self.assertEqual(result.fetch_status, "fetched")
            self.assertTrue((Path(tmp) / "yt1" / "transcript.txt").exists())

    def test_youtube_fetch_degrades_without_transcript(self) -> None:
        oembed = json.dumps({"title": "No Captions", "author_name": "Someone"}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", return_value=(oembed, "url", "application/json")), \
                 patch("prism.fetch._youtube_transcript", side_effect=RuntimeError("transcripts disabled")):
                result = fetch_source("https://youtu.be/dQw4w9WgXcQ", Path(tmp), "yt2")
            self.assertEqual(result.fetch_status, "fetched")
            self.assertEqual(result.title, "No Captions")
            self.assertIn("transcripts disabled", result.metadata.get("transcript_error", ""))
            self.assertFalse((Path(tmp) / "yt2" / "transcript.txt").exists())


class HuggingFaceFetchTests(unittest.TestCase):
    def test_model_fetch_archives_card_and_metadata(self) -> None:
        api = json.dumps({
            "downloads": 1234, "likes": 56, "pipeline_tag": "text-generation",
            "lastModified": "2025-01-02T00:00:00Z", "tags": ["llm", "chat"],
            "cardData": {"license": "apache-2.0"},
        }).encode()
        readme = b"# Llama model card\nDetails here."
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", side_effect=[
                (api, "https://huggingface.co/api/models/meta-llama/Llama-3-8B", "application/json"),
                (readme, "https://huggingface.co/meta-llama/Llama-3-8B/raw/main/README.md", "text/markdown"),
            ]):
                result = fetch_source("https://huggingface.co/meta-llama/Llama-3-8B", Path(tmp), "hf1")
            self.assertEqual(result.source_kind, "huggingface")
            self.assertEqual(result.title, "meta-llama/Llama-3-8B")
            self.assertIn("Downloads: 1234", result.extracted_text)
            self.assertIn("Task: text-generation", result.extracted_text)
            self.assertIn("License: apache-2.0", result.extracted_text)
            self.assertIn("Llama model card", result.extracted_text)
            self.assertTrue((Path(tmp) / "hf1" / "readme.md").exists())

    def test_dataset_fetch_uses_dataset_paths(self) -> None:
        api = json.dumps({"downloads": 9, "likes": 1}).encode()
        readme = b"# Dataset card"
        captured: list[str] = []

        def fake_get(url, headers=None):
            captured.append(url)
            if "/api/datasets/" in url:
                return api, url, "application/json"
            return readme, url, "text/markdown"

        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._http_get_bytes", side_effect=fake_get):
                result = fetch_source("https://huggingface.co/datasets/org/name", Path(tmp), "hf2")
        self.assertEqual(result.source_kind, "huggingface")
        self.assertTrue(any("/api/datasets/org/name" in u for u in captured))
        self.assertTrue(any("/datasets/org/name/raw/main/README.md" in u for u in captured))

    def test_paper_url_delegates_to_arxiv(self) -> None:
        sentinel = FetchResult(
            source_url="x", resolved_url="x", source_kind="paper", title="t", summary=None,
            extracted_text="abs", local_archive=None, pdf_path=None, content_hash="h",
            fetch_status="fetched", fetch_error=None, fetched_at="2026-01-01T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._fetch_arxiv", return_value=sentinel) as mock_arxiv:
                result = fetch_source("https://huggingface.co/papers/2106.01345", Path(tmp), "hf3")
            self.assertIs(result, sentinel)
            called_url = mock_arxiv.call_args[0][0]
            self.assertEqual(called_url, "https://arxiv.org/abs/2106.01345")


class ReadMoreLinkTests(unittest.TestCase):
    def test_extracts_read_more_targets_only(self) -> None:
        html = """
        <p>Item one <a href="https://github.com/o/r">Read more</a></p>
        <p>Item two <a href="/relative/path">Read more →</a></p>
        <p><a href="https://sponsor.com/x">Use my link for 12% OFF</a></p>
        <p>Item three <a href="https://a.com"><span>read more</span></a></p>
        <p>dup <a href="https://github.com/o/r">Read more</a></p>
        """
        links = extract_read_more_links(html, "https://blog.com/post")
        self.assertEqual(links, [
            "https://github.com/o/r",
            "https://blog.com/relative/path",  # relative resolved against base
            "https://a.com",                    # text inside nested span still matches
        ])


class UploadFetchTests(unittest.TestCase):
    def test_fetch_upload_archives_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("prism.fetch._extract_pdf", return_value=("PDF body text", {})):
                result = fetch_upload(b"%PDF-1.4 data", "My File.pdf", Path(tmp), "up1", "application/pdf")
            self.assertEqual(result.source_kind, "pdf")
            self.assertEqual(result.extracted_text, "PDF body text")
            self.assertEqual(result.fetch_status, "fetched")
            self.assertTrue(result.source_url.startswith("upload://"))
            self.assertIsNotNone(result.content_hash)
            self.assertTrue((Path(tmp) / "up1" / "source.pdf").exists())
            self.assertTrue((Path(tmp) / "up1" / "extracted.txt").exists())

    def test_fetch_upload_rejects_non_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = fetch_upload(b"plain", "notes.txt", Path(tmp), "up2", "text/plain")
            self.assertEqual(result.fetch_status, "failed")
            self.assertIn("Unsupported upload type", result.fetch_error or "")


class SaveUploadDedupTests(unittest.TestCase):
    def _service(self, root: Path) -> NoteService:
        db = PrismDatabase(root / "prism.sqlite3")
        llm = LLMConfig("https://example.com", None, None)  # unconfigured -> llm skipped
        indexer = NoteIndexer(root / "lancedb", EmbeddingConfig("https://example.com", None, None))
        return NoteService(root / "vault", db, root / "archives", llm, indexer)

    def test_save_upload_dedups_identical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(Path(tmp))
            with patch("prism.fetch._extract_pdf", return_value=("stable text", {})):
                first = service.save_upload("doc.pdf", b"%PDF bytes", "application/pdf", "telegram")
                second = service.save_upload("doc.pdf", b"%PDF bytes", "application/pdf", "telegram")
            self.assertTrue(first.created)
            self.assertEqual(first.record.source_kind, "pdf")
            self.assertEqual(first.record.input_source, "telegram")
            self.assertFalse(second.created)
            self.assertIn(second.duplicate_reason, {"source_url", "content_hash"})


class InputSourceTests(unittest.TestCase):
    def test_roundtrip_and_default(self) -> None:
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
                summary="S",
                source_kind="website",
                input_source="web_ui",
                fetch_status="fetched",
            )
            db.insert_note(record)
            stored = db.find_by_note_id("abc123")
            assert stored is not None
            self.assertEqual(stored.input_source, "web_ui")
            by_src = db.list_notes_by_input_source("web_ui", 10)
            self.assertEqual([r.note_id for r in by_src], ["abc123"])

    def test_migrated_row_defaults_to_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "prism.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE notes (
                    note_id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE, resolved_url TEXT NOT NULL,
                    note_path TEXT NOT NULL, date_saved TEXT NOT NULL, status TEXT NOT NULL,
                    title TEXT NOT NULL, summary TEXT NOT NULL)"""
            )
            conn.execute(
                "INSERT INTO notes VALUES ('old1','https://e.com','https://e.com','notes/e.md','2026-01-01T00:00:00Z','unreviewed','T','S')"
            )
            conn.commit()
            conn.close()
            db = PrismDatabase(db_path)
            record = db.find_by_note_id("old1")
            assert record is not None
            self.assertEqual(record.input_source, "unknown")

    def test_job_relevant_column_migrates_to_favorite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "prism.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE notes (
                    note_id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE, resolved_url TEXT NOT NULL,
                    note_path TEXT NOT NULL, date_saved TEXT NOT NULL, status TEXT NOT NULL,
                    title TEXT NOT NULL, summary TEXT NOT NULL,
                    job_relevant INTEGER NOT NULL DEFAULT 0)"""
            )
            conn.execute(
                "INSERT INTO notes VALUES ('old1','https://e.com','https://e.com','notes/e.md','2026-01-01T00:00:00Z','unreviewed','T','S',1)"
            )
            conn.commit()
            conn.close()
            db = PrismDatabase(db_path)
            record = db.find_by_note_id("old1")
            assert record is not None
            self.assertEqual(record.favorite, 1)
            self.assertEqual([r.note_id for r in db.list_favorite_notes()], ["old1"])

    def test_render_note_includes_input_source(self) -> None:
        record = NoteRecord(
            note_id="abc123",
            source_url="https://a.example",
            resolved_url="https://a.example",
            note_path="notes/a.md",
            date_saved="2026-01-01T00:00:00Z",
            status="unreviewed",
            title="A",
            summary="S",
            source_kind="website",
            input_source="telegram",
            fetch_status="fetched",
        )
        self.assertIn("input_source: telegram", render_note(record))


if __name__ == "__main__":
    unittest.main()

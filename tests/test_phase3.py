from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from prism.db import NoteRecord, PrismDatabase
from prism.fetch import FetchResult
from prism.llm import LLMClient, LLMConfig, LLMGeneration
from prism.notes import NoteService, render_note


def fetch_result(root: Path, text: str = "Extracted article text") -> FetchResult:
    archive = root / "archives" / "abc123"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "extracted.txt").write_text(text, encoding="utf-8")
    return FetchResult(
        source_url="https://example.com/article",
        resolved_url="https://example.com/article",
        source_kind="website",
        title="Fetched Title",
        summary="Description",
        extracted_text=text,
        local_archive=str(archive),
        pdf_path=None,
        content_hash="hash-phase3",
        fetch_status="fetched",
        fetch_error=None,
        fetched_at="2026-01-01T00:00:00Z",
        metadata={"title": "Fetched Title"},
    )


def structured() -> dict[str, object]:
    return {
        "title": "Generated Title",
        "quick_summary": "Fast practical summary.",
        "detailed_summary": "Medium structured summary for /more.",
        "key_claims": ["Claim one", "Claim two"],
        "limitations": ["Needs validation"],
        "technical_details": ["Uses a small controller"],
        "why_it_matters": "It is useful for robotics systems.",
        "personal_relevance": "Relevant to VLA and manipulation work.",
        "project_ideas": ["Build a small demo"],
        "tags": ["Robotics", "VLA"],
        "relevance": 9,
        "novelty": 7,
        "credibility": 8,
        "actionability": 8,
        "interest": 9,
        "overall": 8.5,
        "confidence": "medium",
    }


class Phase3LLMClientTests(unittest.TestCase):
    def test_http_400_response_format_retries_without_response_format(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeClient:
            def __init__(self, timeout) -> None:
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def post(self, url, headers, json):
                calls.append(json)
                if len(calls) == 1:
                    response = httpx.Response(400, request=httpx.Request("POST", url))
                    raise httpx.HTTPStatusError("bad response_format", request=response.request, response=response)
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"model": "model-a", "choices": [{"message": {"content": json_module.dumps(structured())}}]},
                )

        import json as json_module

        with patch("prism.llm.httpx.Client", FakeClient):
            generation = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).generate_note({"title": "T"}, "profile")

        self.assertEqual(generation.data["title"], "Generated Title")
        self.assertIn("response_format", calls[0])
        self.assertNotIn("response_format", calls[1])

    def test_generate_note_accepts_wrapped_json_object(self) -> None:
        class FakeClient:
            def __init__(self, timeout) -> None:
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def post(self, url, headers, json):
                content = "Here is the JSON:\n```json\n" + json_module.dumps(structured()) + "\n```"
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"model": "model-a", "choices": [{"message": {"content": content}}]},
                )

        import json as json_module

        with patch("prism.llm.httpx.Client", FakeClient):
            generation = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).generate_note({"title": "T"}, "profile")

        self.assertEqual(generation.data["title"], "Generated Title")


class LLMRetryTests(unittest.TestCase):
    def _client(self) -> LLMClient:
        return LLMClient(LLMConfig("https://llm.example", "key", "model-a"))

    @staticmethod
    def _ok_response(url):
        return httpx.Response(
            200, request=httpx.Request("POST", url),
            json={"model": "model-a", "choices": [{"message": {"content": json.dumps(structured())}}],
                  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        )

    def test_retries_transient_then_succeeds(self) -> None:
        calls: list[int] = []

        class FakeClient:
            def __init__(self, timeout) -> None: ...
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def post(self, url, headers, json):
                calls.append(1)
                if len(calls) <= 2:
                    raise httpx.ConnectError("boom")
                return LLMRetryTests._ok_response(url)

        with patch("prism.llm.httpx.Client", FakeClient), patch("prism.llm.time.sleep"):
            gen = self._client().generate_note({"title": "T"}, "profile")
        self.assertEqual(len(calls), 3)
        self.assertEqual(gen.data["title"], "Generated Title")

    def test_does_not_retry_4xx(self) -> None:
        calls: list[int] = []

        class FakeClient:
            def __init__(self, timeout) -> None: ...
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def post(self, url, headers, json):
                calls.append(1)
                resp = httpx.Response(401, request=httpx.Request("POST", url))
                raise httpx.HTTPStatusError("unauthorized", request=resp.request, response=resp)

        with patch("prism.llm.httpx.Client", FakeClient), patch("prism.llm.time.sleep"):
            with self.assertRaises(httpx.HTTPStatusError):
                self._client()._post({"model": "model-a"})
        self.assertEqual(len(calls), 1)  # not retried

    def test_logs_token_usage(self) -> None:
        class FakeClient:
            def __init__(self, timeout) -> None: ...
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def post(self, url, headers, json):
                return LLMRetryTests._ok_response(url)

        with patch("prism.llm.httpx.Client", FakeClient):
            with self.assertLogs("prism.llm", level="INFO") as cm:
                self._client().generate_note({"title": "T"}, "profile")
        self.assertTrue(any("LLM usage" in line and "total=15" in line for line in cm.output))


class Phase3DatabaseTests(unittest.TestCase):
    def test_migrates_phase2_schema_with_llm_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "prism.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE notes (
                    note_id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE, resolved_url TEXT NOT NULL,
                    note_path TEXT NOT NULL, date_saved TEXT NOT NULL, status TEXT NOT NULL,
                    title TEXT NOT NULL, summary TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT 'unknown',
                    local_archive TEXT, pdf_path TEXT, content_hash TEXT,
                    fetch_status TEXT NOT NULL DEFAULT 'not_fetched', fetch_error TEXT, fetched_at TEXT, metadata_json TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO notes VALUES (
                    'abc123', 'https://example.com', 'https://example.com', 'notes/example.md',
                    '2026-01-01T00:00:00Z', 'unreviewed', 'Old title', 'Old summary',
                    'website', NULL, NULL, NULL, 'fetched', NULL, '2026-01-01T00:00:00Z', '{}')
                """
            )
            conn.commit()
            conn.close()

            db = PrismDatabase(db_path)
            record = db.find_by_note_id("abc123")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.llm_status, "skipped")
            self.assertIsNone(record.structured_summary_json)


class Phase3NoteServiceTests(unittest.TestCase):
    def test_llm_config_missing_saves_archive_note_with_skipped_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", None, None))
            with patch("prism.notes.fetch_source", return_value=fetch_result(root)):
                result = service.save_url("https://example.com/article")

            self.assertEqual(result.record.llm_status, "skipped")
            note_text = (root / "vault" / result.record.note_path).read_text(encoding="utf-8")
            self.assertIn("llm_status: skipped", note_text)
            self.assertIn("summary_status: placeholder", note_text)

    def test_mocked_llm_success_updates_record_frontmatter_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))
            generation = LLMGeneration(structured(), "model-a")

            with patch("prism.notes.fetch_source", return_value=fetch_result(root)), patch("prism.notes.LLMClient.generate_note", return_value=generation):
                result = service.save_url("https://example.com/article")

            self.assertEqual(result.record.title, "Generated Title")
            self.assertEqual(result.record.summary, "Fast practical summary.")
            self.assertEqual(result.record.llm_status, "generated")
            self.assertEqual(json.loads(result.record.tags_json or "[]"), ["robotics", "vla"])
            note_text = (root / "vault" / result.record.note_path).read_text(encoding="utf-8")
            self.assertIn("summary_status: generated", note_text)
            self.assertIn("llm_model: model-a", note_text)
            self.assertIn("relevance_score: 9", note_text)
            self.assertIn("## Detailed Summary", note_text)
            self.assertIn("Claim one", note_text)

    def test_malformed_llm_response_falls_back_with_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))

            with patch("prism.notes.fetch_source", return_value=fetch_result(root)), patch("prism.notes.LLMClient.generate_note", side_effect=ValueError("bad json")):
                result = service.save_url("https://example.com/article")

            self.assertEqual(result.record.llm_status, "failed")
            self.assertIn("bad json", result.record.llm_error or "")
            note_text = (root / "vault" / result.record.note_path).read_text(encoding="utf-8")
            self.assertIn("summary_status: placeholder", note_text)
            self.assertIn("LLM status: failed", note_text)

    def test_profile_created_once_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives")
            profile = service.profile_path
            self.assertTrue(profile.exists())
            self.assertIn("Copenhagen/Lyngby", profile.read_text(encoding="utf-8"))

            profile.write_text("custom profile", encoding="utf-8")
            NoteService(root / "vault", db, root / "archives")
            self.assertEqual(profile.read_text(encoding="utf-8"), "custom profile")

    def test_reprocess_rejects_missing_unfetched_and_archive_less_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))
            self.assertFalse(service.reprocess("missing").ok)

            unfetched = NoteRecord(
                note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="A", summary="A", fetch_status="failed"
            )
            db.insert_note(unfetched)
            self.assertFalse(service.reprocess("abc123").ok)

            no_archive = NoteRecord(
                note_id="def456", source_url="https://b", resolved_url="https://b", note_path="notes/b.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="B", summary="B", fetch_status="fetched"
            )
            db.insert_note(no_archive)
            self.assertFalse(service.reprocess("def456").ok)

    def test_reprocess_succeeds_for_fetched_note_with_archived_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))
            archive = root / "archives" / "abc123"
            archive.mkdir(parents=True)
            (archive / "extracted.txt").write_text("Archived text", encoding="utf-8")
            note_path = root / "vault" / "notes" / "a.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text("old", encoding="utf-8")
            record = NoteRecord(
                note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="A", summary="A",
                fetch_status="fetched", source_kind="website", local_archive=str(archive), metadata_json="{}"
            )
            db.insert_note(record)

            with patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")):
                result = service.reprocess("abc123")

            self.assertTrue(result.ok)
            assert result.record is not None
            self.assertEqual(result.record.llm_status, "generated")
            self.assertIn("Generated Title", note_path.read_text(encoding="utf-8"))
            self.assertEqual(db.find_by_note_id("abc123").title, "Generated Title")

    def test_reprocess_recovers_empty_website_extraction_from_raw_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))
            archive = root / "archives" / "abc123"
            archive.mkdir(parents=True)
            (archive / "extracted.txt").write_text("", encoding="utf-8")
            (archive / "raw.html").write_text("<html><iframe src='embedded.html'></iframe></html>", encoding="utf-8")
            note_path = root / "vault" / "notes" / "a.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text("old", encoding="utf-8")
            record = NoteRecord(
                note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="A", summary="A",
                fetch_status="fetched", source_kind="website", local_archive=str(archive), metadata_json="{}"
            )
            db.insert_note(record)

            with patch("prism.notes.extract_website_text", return_value=("A", "Recovered website text", {"extraction_fallback": "embedded_html"})), patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")):
                result = service.reprocess("abc123")

            self.assertTrue(result.ok)
            self.assertEqual((archive / "extracted.txt").read_text(encoding="utf-8"), "Recovered website text")
            stored = db.find_by_note_id("abc123")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertIn("embedded_html", stored.metadata_json or "")


class NoteEditTests(unittest.TestCase):
    def _service_with_note(self, root: Path):
        db = PrismDatabase(root / "prism.sqlite3")
        service = NoteService(root / "vault", db, root / "archives")  # no LLM/indexer
        note_path = root / "vault" / "notes" / "a.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("old", encoding="utf-8")
        record = NoteRecord(
            note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
            date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="Old Title", summary="A",
            fetch_status="fetched", source_kind="website",
        )
        db.insert_note(record)
        return db, service, record, note_path

    def test_rename_note_updates_db_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, service, record, note_path = self._service_with_note(root)
            updated = service.rename_note(record, "  A   Better  Title ")
            self.assertEqual(updated.title, "A Better Title")
            self.assertEqual(db.find_by_note_id("abc123").title, "A Better Title")
            self.assertIn("title: A Better Title", note_path.read_text(encoding="utf-8"))

    def test_rename_note_rejects_empty_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, service, record, _ = self._service_with_note(root)
            with self.assertRaises(ValueError):
                service.rename_note(record, "   ")

    def test_set_status_updates_db_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, service, record, note_path = self._service_with_note(root)
            updated = service.set_status(record, "reviewed")
            self.assertEqual(updated.status, "reviewed")
            self.assertEqual(db.find_by_note_id("abc123").status, "reviewed")
            self.assertIn("status: reviewed", note_path.read_text(encoding="utf-8"))

    def test_set_status_rejects_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, service, record, _ = self._service_with_note(root)
            with self.assertRaises(ValueError):
                service.set_status(record, "bogus")

    def test_search_keyword_only_without_indexer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives")  # no indexer
            db.insert_note(NoteRecord(
                note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="Diffusion models survey",
                summary="a survey of diffusion", source_kind="paper", llm_status="generated",
            ))
            results = service.search("diffusion")
            self.assertTrue(any(c.note_id == "abc123" for c in results))


class Phase3RenderTests(unittest.TestCase):
    def test_renderer_handles_missing_structured_fields(self) -> None:
        record = NoteRecord(
            note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
            date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="A", summary="Quick",
            fetch_status="fetched", llm_status="generated", structured_summary_json=json.dumps({"title": "A"})
        )
        note = render_note(record, "body")
        self.assertIn("Not provided.", note)
        self.assertIn("summary_status: generated", note)


if __name__ == "__main__":
    unittest.main()

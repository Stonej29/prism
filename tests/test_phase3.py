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
from prism.index import canonical_index_text
from prism.llm import LLMClient, LLMConfig, LLMGeneration
from prism.notes import NoteService, normalize_purpose, render_note, scores_for_record, structured_summary, tags_for_record


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


def personalization() -> dict[str, object]:
    """The call-2 (personalization) subset, matching the values in ``structured()``."""
    return {
        "why_it_matters": "It is useful for robotics systems.",
        "personal_relevance": "Relevant to VLA and manipulation work.",
        "project_ideas": ["Build a small demo"],
        "relevance": 9,
        "actionability": 8,
        "interest": 9,
        "overall": 8.5,
    }


def _patch_personalize():
    """Patch the personalization pass so save/reprocess never touches the network."""
    return patch("prism.notes.LLMClient.personalize_note", return_value=LLMGeneration(personalization(), "model-a"))


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
            generation = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).generate_note({"title": "T"})

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
            generation = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).generate_note({"title": "T"})

        self.assertEqual(generation.data["title"], "Generated Title")

    def test_generate_note_web_mode_enables_openrouter_plugin(self) -> None:
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
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"model": "model-a", "choices": [{"message": {"content": json_module.dumps(structured())}}]},
                )

        import json as json_module

        with patch("prism.llm.httpx.Client", FakeClient):
            generation = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).generate_note({"title": "T"}, web=True)

        self.assertEqual(generation.data["title"], "Generated Title")
        self.assertEqual(calls[0]["plugins"], [{"id": "web"}])

    def test_generate_note_web_400_drops_plugin_then_succeeds(self) -> None:
        import json as json_module

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
                # 400 while either response_format or the web plugin is present.
                if "response_format" in json or "plugins" in json:
                    return httpx.Response(400, request=httpx.Request("POST", url), json={"error": "bad"})
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={"model": "model-a", "choices": [{"message": {"content": json_module.dumps(structured())}}]},
                )

        with patch("prism.llm.httpx.Client", FakeClient):
            generation = LLMClient(LLMConfig("https://llm.example", "key", "model-a")).generate_note({"title": "T"}, web=True)

        self.assertEqual(generation.data["title"], "Generated Title")
        # Progressive fallback: rf+web → rf dropped (web kept) → web dropped.
        self.assertEqual(len(calls), 3)
        self.assertNotIn("plugins", calls[2])
        self.assertNotIn("response_format", calls[2])


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
            gen = self._client().generate_note({"title": "T"})
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
                self._client().generate_note({"title": "T"})
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


class NormalizePurposeTests(unittest.TestCase):
    def test_canonicalizes_loose_input(self) -> None:
        self.assertEqual(normalize_purpose("self host"), "Self-Host")
        self.assertEqual(normalize_purpose("SELF_HOST"), "Self-Host")
        self.assertEqual(normalize_purpose("thesis"), "Thesis")
        self.assertEqual(normalize_purpose("Dataset"), "Dataset")

    def test_unknown_and_empty_become_none(self) -> None:
        self.assertIsNone(normalize_purpose("made up"))
        self.assertIsNone(normalize_purpose(""))
        self.assertIsNone(normalize_purpose(None))


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

            with patch("prism.notes.fetch_source", return_value=fetch_result(root)), patch("prism.notes.LLMClient.generate_note", return_value=generation), _patch_personalize():
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

    def test_personalization_classifies_and_persists_purpose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))
            generation = LLMGeneration(structured(), "model-a")
            # The cheap personalization pass returns a loosely-cased purpose; it should
            # canonicalize to "Self-Host" and be marked as an AI ("auto") classification.
            personalize = patch(
                "prism.notes.LLMClient.personalize_note",
                return_value=LLMGeneration({**personalization(), "purpose": "self host"}, "model-a"),
            )

            with patch("prism.notes.fetch_source", return_value=fetch_result(root)), patch("prism.notes.LLMClient.generate_note", return_value=generation), personalize:
                result = service.save_url("https://example.com/article")

            self.assertEqual(result.record.purpose, "Self-Host")
            stored = db.find_by_note_id(result.record.note_id)
            self.assertEqual(stored.purpose, "Self-Host")
            self.assertEqual(stored.purpose_source, "auto")
            note_text = (root / "vault" / result.record.note_path).read_text(encoding="utf-8")
            self.assertIn("purpose: Self-Host", note_text)

    def test_reading_minutes_stored_in_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://x", None, None))
            long_text = " ".join(["word"] * 600)  # 600 words ~ 3 min at 200 wpm
            with patch("prism.notes.fetch_source", return_value=fetch_result(root, long_text)):
                result = service.save_url("https://example.com/article")
            meta = json.loads(result.record.metadata_json or "{}")
            self.assertEqual(meta.get("reading_minutes"), 3)

    def test_unrecognized_purpose_becomes_unsorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))
            generation = LLMGeneration({**structured(), "purpose": "made up"}, "model-a")

            with patch("prism.notes.fetch_source", return_value=fetch_result(root)), patch("prism.notes.LLMClient.generate_note", return_value=generation), _patch_personalize():
                result = service.save_url("https://example.com/article")

            self.assertIsNone(result.record.purpose)

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
            self.assertIn("Describe the person using PRISM here", profile.read_text(encoding="utf-8"))

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

            with patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")), _patch_personalize():
                result = service.reprocess("abc123")

            self.assertTrue(result.ok)
            assert result.record is not None
            self.assertEqual(result.record.llm_status, "generated")
            self.assertIn("Generated Title", note_path.read_text(encoding="utf-8"))
            self.assertEqual(db.find_by_note_id("abc123").title, "Generated Title")


    def test_research_note_uses_web_generation_and_records_metadata(self) -> None:
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

            with patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")) as generate, _patch_personalize():
                result = service.research_note("abc123")

            self.assertTrue(result.ok)
            self.assertTrue(generate.call_args.kwargs["web"])
            self.assertIn("research_request", generate.call_args.args[0])
            saved = db.find_by_note_id("abc123")
            self.assertIsNotNone(saved)
            metadata = json.loads(saved.metadata_json)
            self.assertEqual(metadata["research_status"], "generated")
            self.assertIn("researched_at", metadata)

    def test_research_note_records_web_sources(self) -> None:
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
            db.insert_note(NoteRecord(
                note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="A", summary="A",
                fetch_status="fetched", source_kind="website", local_archive=str(archive), metadata_json="{}",
            ))
            gen = LLMGeneration(structured(), "model-a", web_sources=[{"url": "https://src.example/x", "title": "X"}])
            with patch("prism.notes.LLMClient.generate_note", return_value=gen), _patch_personalize():
                result = service.research_note("abc123")
            self.assertTrue(result.ok)
            metadata = json.loads(db.find_by_note_id("abc123").metadata_json)
            self.assertEqual(metadata["research_sources"][0]["url"], "https://src.example/x")

    def test_reprocess_refetches_failed_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", LLMConfig("https://llm.example", "key", "model-a"))
            note_path = root / "vault" / "notes" / "a.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text("old", encoding="utf-8")
            db.insert_note(NoteRecord(
                note_id="abc123", source_url="https://blocked", resolved_url="https://blocked", note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="A", summary="A",
                fetch_status="failed", source_kind="website", metadata_json="{}",
            ))

            def fake_fetch(url, archive_root, note_id):
                d = archive_root / note_id
                d.mkdir(parents=True, exist_ok=True)
                (d / "extracted.txt").write_text("Recovered body text", encoding="utf-8")
                return FetchResult(
                    source_url=url, resolved_url=url, source_kind="website", title="A", summary=None,
                    extracted_text="Recovered body text", local_archive=str(d), pdf_path=None, content_hash="h",
                    fetch_status="fetched", fetch_error=None, fetched_at="2026-01-02T00:00:00Z", metadata={},
                )

            with patch("prism.notes.fetch_source", side_effect=fake_fetch), \
                 patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")), \
                 _patch_personalize():
                result = service.reprocess("abc123")
            self.assertTrue(result.ok)
            self.assertEqual(db.find_by_note_id("abc123").fetch_status, "fetched")

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

            with patch("prism.notes.extract_website_text", return_value=("A", "Recovered website text", {"extraction_fallback": "embedded_html"})), patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")), _patch_personalize():
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


class PersonalizationSplitTests(unittest.TestCase):
    """The two-call split: ground truth (call 1) vs. personalization (call 2)."""

    def _config(self) -> LLMConfig:
        return LLMConfig("https://llm.example", "key", "model-a")

    def _seed_note(self, root: Path, db: PrismDatabase) -> NoteService:
        service = NoteService(root / "vault", db, root / "archives", self._config())  # no indexer
        with patch("prism.notes.fetch_source", return_value=fetch_result(root)), \
             patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")), \
             _patch_personalize():
            service.save_url("https://example.com/article")
        return service

    def test_personalize_payload_carries_profile_and_groundtruth_no_source(self) -> None:
        calls: list[dict] = []

        class FakeClient:
            def __init__(self, timeout) -> None: ...
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def post(self, url, headers, json):
                calls.append(json)
                return httpx.Response(
                    200, request=httpx.Request("POST", url),
                    json={"model": "model-a", "choices": [{"message": {"content": json_lib.dumps(personalization())}}]},
                )

        import json as json_lib

        with patch("prism.llm.httpx.Client", FakeClient):
            LLMClient(self._config()).personalize_note({"title": "T", "quick_summary": "S"}, "my-profile")

        body = json_lib.loads(calls[0]["messages"][1]["content"])
        self.assertEqual(body["profile"], "my-profile")
        self.assertEqual(body["note"]["quick_summary"], "S")
        self.assertNotIn("extracted_text", json_lib.dumps(body))

    def test_personalize_note_400_drops_response_format(self) -> None:
        import json as json_lib
        calls: list[dict] = []

        class FakeClient:
            def __init__(self, timeout) -> None: ...
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def post(self, url, headers, json):
                calls.append(json)
                if "response_format" in json:
                    return httpx.Response(400, request=httpx.Request("POST", url), json={"error": "bad"})
                return httpx.Response(
                    200, request=httpx.Request("POST", url),
                    json={"model": "model-a", "choices": [{"message": {"content": json_lib.dumps(personalization())}}]},
                )

        with patch("prism.llm.httpx.Client", FakeClient):
            gen = LLMClient(self._config()).personalize_note({"title": "T"}, "p")
        self.assertEqual(gen.data["relevance"], 9)
        self.assertIn("response_format", calls[0])
        self.assertNotIn("response_format", calls[1])

    def test_personalization_context_excludes_source_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = self._seed_note(root, db)
            captured: dict = {}

            def fake_personalize(ground_truth, profile, **kwargs):
                captured["gt"] = ground_truth
                captured["profile"] = profile
                captured["kwargs"] = kwargs
                return LLMGeneration(personalization(), "model-a")

            note_id = db.list_notes_for_reindexing()[0].note_id
            with patch("prism.notes.LLMClient.personalize_note", side_effect=fake_personalize):
                service.repersonalize(note_id)
            self.assertNotIn("extracted_text", captured["gt"])
            self.assertEqual(captured["gt"]["quick_summary"], "Fast practical summary.")
            self.assertIn("Personal Profile", captured["profile"])

    def test_repersonalize_only_changes_personal_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = self._seed_note(root, db)
            before = db.list_notes_for_reindexing()[0]
            idx_before = canonical_index_text(before)
            tags_before = tags_for_record(before)
            related_before = before.related_notes_json
            novelty_before = scores_for_record(before)["novelty"]
            detail_before = structured_summary(before)["detailed_summary"]

            new_personal = {
                "why_it_matters": "Totally different angle.",
                "personal_relevance": "Now only mildly relevant.",
                "project_ideas": ["A different demo"],
                "relevance": 3, "actionability": 2, "interest": 4, "overall": 3,
            }
            with patch("prism.notes.LLMClient.personalize_note", return_value=LLMGeneration(new_personal, "model-a")):
                result = service.repersonalize(before.note_id)
            self.assertTrue(result.ok)
            after = result.record
            scores_after = scores_for_record(after)
            struct_after = structured_summary(after)

            # Personal fields/scores updated...
            self.assertEqual(scores_after["relevance"], 3)
            self.assertEqual(scores_after["overall"], 3)
            self.assertEqual(struct_after["why_it_matters"], "Totally different angle.")
            # ...while ground truth is untouched (so the embedding never changes).
            self.assertEqual(scores_after["novelty"], novelty_before)
            self.assertEqual(tags_for_record(after), tags_before)
            self.assertEqual(after.related_notes_json, related_before)
            self.assertEqual(struct_after["detailed_summary"], detail_before)
            self.assertEqual(canonical_index_text(after), idx_before)

    def test_repersonalize_does_not_relabel_classified_purpose(self) -> None:
        import dataclasses
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = self._seed_note(root, db)
            # An already-classified (auto) note.
            before = db.list_notes_for_reindexing()[0]
            db.update_note(dataclasses.replace(before, purpose="Work", purpose_source="auto"))

            # The classifier now suggests a different purpose, but repersonalize must NOT
            # silently relabel an already-classified note (that goes through proposals).
            moved = {**personalization(), "purpose": "Thesis"}
            with patch("prism.notes.LLMClient.personalize_note", return_value=LLMGeneration(moved, "model-a")):
                result = service.repersonalize(before.note_id)
            self.assertTrue(result.ok)
            self.assertEqual(result.record.purpose, "Work")
            self.assertEqual(result.record.purpose_source, "auto")

    def test_repersonalize_rejects_ungenerated_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = NoteService(root / "vault", db, root / "archives", self._config())
            db.insert_note(NoteRecord(
                note_id="abc123", source_url="https://a", resolved_url="https://a", note_path="notes/a.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="A", summary="A",
                fetch_status="fetched", llm_status="failed",
            ))
            result = service.repersonalize("abc123")
            self.assertFalse(result.ok)
            self.assertIn("LLM status", result.message)

    def test_repersonalize_all_counts_only_generated_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = self._seed_note(root, db)  # 1 generated note
            db.insert_note(NoteRecord(
                note_id="skip01", source_url="https://b", resolved_url="https://b", note_path="notes/b.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="B", summary="B",
                fetch_status="fetched", llm_status="skipped",
            ))
            with patch("prism.notes.LLMClient.personalize_note", return_value=LLMGeneration(personalization(), "model-a")):
                summary = service.repersonalize_all()
            self.assertEqual(summary.total, 1)
            self.assertEqual(summary.updated, 1)
            self.assertEqual(summary.failed, 0)

    def test_reprocess_all_reprocesses_fetched_notes_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = self._seed_note(root, db)  # 1 fetched + generated note (has archive)
            db.insert_note(NoteRecord(
                note_id="unfetched01", source_url="https://b", resolved_url="https://b", note_path="notes/b.md",
                date_saved="2026-01-01T00:00:00Z", status="unreviewed", title="B", summary="B",
                fetch_status="failed", llm_status="skipped",
            ))
            with patch("prism.notes.LLMClient.generate_note", return_value=LLMGeneration(structured(), "model-a")), \
                 _patch_personalize():
                summary = service.reprocess_all()
            # The un-fetched note is skipped (no archive to reprocess from).
            self.assertEqual(summary.total, 1)
            self.assertEqual(summary.reprocessed, 1)
            self.assertEqual(summary.failed, 0)

    def test_profile_update_triggers_bulk_repersonalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PrismDatabase(root / "prism.sqlite3")
            service = self._seed_note(root, db)
            with patch("prism.notes.LLMClient.rewrite_profile", return_value="# Personal Profile\n\nNew interests."), \
                 patch("prism.notes.LLMClient.personalize_note", return_value=LLMGeneration(personalization(), "model-a")):
                result = service.update_profile("now into reinforcement learning")
            self.assertTrue(result.ok)
            self.assertIn("Re-personalized 1/1", result.message)


class Phase12DedupTests(unittest.TestCase):
    def _service(self, root: Path) -> NoteService:
        db = PrismDatabase(root / "prism.sqlite3")
        return NoteService(root / "vault", db, root / "archives", LLMConfig("https://x", None, None))

    def _fetch(self, root: Path, *, source_url: str, resolved_url: str | None = None, content_hash: str = "h1") -> FetchResult:
        archive = root / "archives" / "shared"
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "extracted.txt").write_text("body text", encoding="utf-8")
        return FetchResult(
            source_url=source_url,
            resolved_url=resolved_url or source_url,
            source_kind="website",
            title="A Title",
            summary="Desc",
            extracted_text="body text",
            local_archive=str(archive),
            pdf_path=None,
            content_hash=content_hash,
            fetch_status="fetched",
            fetch_error=None,
            fetched_at="2026-01-01T00:00:00Z",
            metadata={},
        )

    def test_content_hash_duplicate_and_force_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self._service(root)
            with patch("prism.notes.fetch_source", return_value=self._fetch(root, source_url="https://a.com/1", content_hash="dup")):
                first = service.save_url("https://a.com/1")
            self.assertTrue(first.created)

            # A different URL with identical content is a content_hash duplicate.
            with patch("prism.notes.fetch_source", return_value=self._fetch(root, source_url="https://b.com/2", content_hash="dup")):
                dup = service.save_url("https://b.com/2")
            self.assertFalse(dup.created)
            self.assertEqual(dup.duplicate_reason, "content_hash")
            self.assertEqual(dup.record.note_id, first.record.note_id)

            # force=True bypasses the check and creates a fresh note.
            with patch("prism.notes.fetch_source", return_value=self._fetch(root, source_url="https://b.com/2", content_hash="dup")):
                forced = service.save_url("https://b.com/2", force=True)
            self.assertTrue(forced.created)
            self.assertNotEqual(forced.record.note_id, first.record.note_id)

    def test_resolved_url_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self._service(root)
            with patch("prism.notes.fetch_source", return_value=self._fetch(root, source_url="https://canonical.com/x", content_hash="h1")):
                first = service.save_url("https://canonical.com/x")
            self.assertTrue(first.created)

            # A shortener resolving to the same final URL (different content hash) is caught.
            with patch("prism.notes.fetch_source", return_value=self._fetch(root, source_url="https://sho.rt/abc", resolved_url="https://canonical.com/x", content_hash="h2")):
                dup = service.save_url("https://sho.rt/abc")
            self.assertFalse(dup.created)
            self.assertEqual(dup.duplicate_reason, "resolved_url")
            self.assertEqual(dup.record.note_id, first.record.note_id)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism.db import NoteRecord, PrismDatabase, ProposalRecord
from prism.embedding import EmbeddingConfig
from prism.index import NoteIndexer
from prism.llm import LLMConfig, LLMGeneration
from prism.notes import NoteService, related_notes_for_record, tags_for_record
from prism.proposals import KIND_MERGE, ProposalService
from prism.services import Services
from prism.worker.traversal import build_canonical_tag_map, run_graph_traversal


def make_note(note_id: str, *, overall: float = 5.0, tags: tuple[str, ...] = ()) -> NoteRecord:
    return NoteRecord(
        note_id=note_id,
        source_url=f"https://example.com/{note_id}",
        resolved_url=f"https://example.com/{note_id}",
        note_path=f"notes/{note_id}.md",
        date_saved=f"2026-05-2{len(note_id)}T00:00:00Z",
        status="unreviewed",
        title=f"Note {note_id}",
        summary=f"Summary {note_id}",
        source_kind="website",
        fetch_status="fetched",
        llm_status="generated",
        scores_json=json.dumps({"overall": overall}),
        tags_json=json.dumps(list(tags)) if tags else None,
    )


class _FakeIndexerOff:
    is_configured = False

    def all_vectors(self) -> dict:
        return {}


class ProposalsDBTests(unittest.TestCase):
    def _db(self, tmp: str) -> PrismDatabase:
        return PrismDatabase(Path(tmp) / "prism.sqlite3")

    def test_roundtrip_list_count_dedup_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            rec = ProposalRecord(
                proposal_id="p00001",
                created_at="2026-05-30T00:00:00Z",
                kind=KIND_MERGE,
                status="pending",
                note_ids_json=json.dumps(["a", "b"]),
                payload_json=json.dumps({"keep": "a", "remove": "b"}),
            )
            db.insert_proposal(rec)
            self.assertEqual(db.find_by_proposal_id("p00001"), rec)
            self.assertEqual([p.proposal_id for p in db.list_proposals("pending")], ["p00001"])
            self.assertEqual(db.count_proposals("pending"), 1)
            self.assertTrue(db.pending_proposal_exists(KIND_MERGE, json.dumps(["a", "b"])))
            self.assertFalse(db.pending_proposal_exists(KIND_MERGE, json.dumps(["a", "c"])))

            db.update_proposal_status("p00001", "approved", "2026-05-30T01:00:00Z")
            self.assertEqual(db.count_proposals("pending"), 0)
            self.assertEqual(db.find_by_proposal_id("p00001").status, "approved")
            # No longer pending -> dedup guard frees the pair again.
            self.assertFalse(db.pending_proposal_exists(KIND_MERGE, json.dumps(["a", "b"])))

            self.assertTrue(db.delete_proposal("p00001"))
            self.assertIsNone(db.find_by_proposal_id("p00001"))


class ProposalServiceTests(unittest.TestCase):
    def _service(self, tmp: str) -> tuple[PrismDatabase, ProposalService]:
        db = PrismDatabase(Path(tmp) / "prism.sqlite3")
        notes = NoteService(
            Path(tmp) / "vault",
            db,
            Path(tmp) / "archives",
            LLMConfig("https://e", None, None),
            NoteIndexer(Path(tmp) / "lancedb", EmbeddingConfig("https://e", None, None)),
        )
        return db, ProposalService(db, notes)

    def test_approve_merge_deletes_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, service = self._service(tmp)
            db.insert_note(make_note("aaa", overall=8))
            db.insert_note(make_note("bbb", overall=5))
            db.insert_proposal(ProposalRecord(
                proposal_id="p00001",
                created_at="2026-05-30T00:00:00Z",
                kind=KIND_MERGE,
                note_ids_json=json.dumps(["aaa", "bbb"]),
                payload_json=json.dumps({"keep": "aaa", "remove": "bbb"}),
            ))
            result = service.approve("p00001")
            self.assertTrue(result.ok)
            self.assertIsNone(db.find_by_note_id("bbb"))
            self.assertIsNotNone(db.find_by_note_id("aaa"))
            self.assertEqual(db.find_by_proposal_id("p00001").status, "approved")

    def test_reject_marks_status_and_keeps_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, service = self._service(tmp)
            db.insert_note(make_note("aaa"))
            db.insert_note(make_note("bbb"))
            db.insert_proposal(ProposalRecord(
                proposal_id="p00002",
                created_at="2026-05-30T00:00:00Z",
                kind=KIND_MERGE,
                note_ids_json=json.dumps(["aaa", "bbb"]),
                payload_json=json.dumps({"keep": "aaa", "remove": "bbb"}),
            ))
            result = service.reject("p00002")
            self.assertTrue(result.ok)
            self.assertEqual(db.find_by_proposal_id("p00002").status, "rejected")
            self.assertIsNotNone(db.find_by_note_id("bbb"))

    def test_already_resolved_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, service = self._service(tmp)
            db.insert_note(make_note("aaa"))
            db.insert_note(make_note("bbb"))
            db.insert_proposal(ProposalRecord(
                proposal_id="p00003", created_at="2026-05-30T00:00:00Z", kind=KIND_MERGE,
                note_ids_json=json.dumps(["aaa", "bbb"]),
                payload_json=json.dumps({"keep": "aaa", "remove": "bbb"}),
            ))
            self.assertTrue(service.approve("p00003").ok)
            second = service.approve("p00003")
            self.assertFalse(second.ok)
            self.assertIn("already", second.message)

    def test_missing_proposal_404ish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, service = self._service(tmp)
            result = service.approve("nope99")
            self.assertFalse(result.ok)
            self.assertIsNone(result.record)


class _FakeIndexer:
    is_configured = True

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def all_vectors(self) -> dict[str, list[float]]:
        return self._vectors


class TraversalTests(unittest.TestCase):
    def _services(self, tmp: str, vectors: dict[str, list[float]]) -> Services:
        db = PrismDatabase(Path(tmp) / "prism.sqlite3")
        return Services(
            settings=None,  # type: ignore[arg-type]
            database=db,
            indexer=_FakeIndexer(vectors),  # type: ignore[arg-type]
            notes=None,  # type: ignore[arg-type]
            ideas=None,  # type: ignore[arg-type]
        )

    def test_links_added_and_duplicate_proposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vectors = {"aaa": [1.0, 0.0, 0.0], "bbb": [0.99, 0.01, 0.0], "ccc": [0.0, 1.0, 0.0]}
            services = self._services(tmp, vectors)
            db = services.database
            db.insert_note(make_note("aaa", overall=8))
            db.insert_note(make_note("bbb", overall=5))
            db.insert_note(make_note("ccc", overall=7))

            events: list[dict] = []
            summary = run_graph_traversal(services, emit_event=events.append)
            self.assertEqual(summary.duplicates_proposed, 1)
            self.assertGreaterEqual(summary.links_added, 2)
            kinds = {event["kind"] for event in events}
            self.assertIn("edge_added", kinds)
            self.assertIn("proposal_created", kinds)

            # aaa and bbb are mutually linked; ccc is orthogonal.
            a_links = {item["id"] for item in related_notes_for_record(db.find_by_note_id("aaa"))}
            self.assertIn("bbb", a_links)
            self.assertNotIn("ccc", a_links)

            # Duplicate proposal keeps the higher-scored note (aaa) and removes bbb.
            pending = db.list_proposals("pending")
            self.assertEqual(len(pending), 1)
            payload = json.loads(pending[0].payload_json)
            self.assertEqual(payload["keep"], "aaa")
            self.assertEqual(payload["remove"], "bbb")

    def test_idempotent_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vectors = {"aaa": [1.0, 0.0], "bbb": [0.995, 0.01]}
            services = self._services(tmp, vectors)
            db = services.database
            db.insert_note(make_note("aaa", overall=8))
            db.insert_note(make_note("bbb", overall=5))
            run_graph_traversal(services)
            second = run_graph_traversal(services)
            self.assertEqual(second.duplicates_proposed, 0)
            self.assertEqual(second.links_added, 0)
            self.assertEqual(db.count_proposals("pending"), 1)


def _related(*ids: str) -> str:
    return json.dumps([{"id": i, "title": f"Note {i}", "reason": "r", "path": f"notes/{i}.md"} for i in ids])


class MergeNotesTests(unittest.TestCase):
    def _notes(self, tmp: str, *, configured: bool = False) -> tuple[PrismDatabase, NoteService]:
        db = PrismDatabase(Path(tmp) / "prism.sqlite3")
        llm = LLMConfig("https://e", "key", "model") if configured else LLMConfig("https://e", None, None)
        notes = NoteService(
            Path(tmp) / "vault", db, Path(tmp) / "archives",
            llm, NoteIndexer(Path(tmp) / "lancedb", EmbeddingConfig("https://e", None, None)),
        )
        return db, notes

    def test_structural_merge_unions_and_repoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, notes = self._notes(tmp)  # LLM unconfigured -> structural merge
            db.insert_note(dataclasses.replace(make_note("aaa", overall=8, tags=("rag",)), related_notes_json=_related("ccc")))
            db.insert_note(dataclasses.replace(make_note("bbb", overall=5, tags=("agents",)), related_notes_json=_related("ddd")))
            db.insert_note(dataclasses.replace(make_note("xxx"), related_notes_json=_related("bbb")))  # backlink to the duplicate

            result = notes.merge_notes("aaa", "bbb")
            self.assertTrue(result.ok)
            self.assertFalse(result.synthesized)

            keep = db.find_by_note_id("aaa")
            self.assertEqual(set(tags_for_record(keep)), {"rag", "agents"})           # tags unioned
            self.assertEqual({r["id"] for r in related_notes_for_record(keep)}, {"ccc", "ddd"})  # links unioned
            self.assertIsNone(db.find_by_note_id("bbb"))                                # duplicate gone
            # backlink in xxx re-pointed bbb -> aaa
            self.assertEqual({r["id"] for r in related_notes_for_record(db.find_by_note_id("xxx"))}, {"aaa"})

    def test_llm_merge_synthesizes_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, notes = self._notes(tmp, configured=True)
            db.insert_note(make_note("aaa", overall=8, tags=("rag",)))
            db.insert_note(make_note("bbb", overall=5, tags=("agents",)))

            fake = LLMGeneration(
                data={"title": "Unified Topic", "quick_summary": "combined pitch", "detailed_summary": "d", "overall": 9},
                model="merge-model",
            )
            with patch("prism.notes.LLMClient.merge_notes", lambda self, ctx, profile: fake):
                result = notes.merge_notes("aaa", "bbb")

            self.assertTrue(result.ok)
            self.assertTrue(result.synthesized)
            keep = db.find_by_note_id("aaa")
            self.assertEqual(keep.title, "Unified Topic")
            self.assertEqual(keep.summary, "combined pitch")
            self.assertEqual(keep.llm_status, "generated")
            self.assertEqual(set(tags_for_record(keep)), {"rag", "agents"})  # tags still unioned, not from LLM
            self.assertIsNone(db.find_by_note_id("bbb"))

    def test_merge_missing_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, notes = self._notes(tmp)
            db.insert_note(make_note("aaa"))
            result = notes.merge_notes("aaa", "zzz")
            self.assertFalse(result.ok)


class TagNormalizationTests(unittest.TestCase):
    def test_build_canonical_tag_map(self) -> None:
        mapping = build_canonical_tag_map([
            ("foundation-model", 1), ("foundation-models", 1),
            ("agents", 3), ("agent", 1),
            ("policy", 2), ("policies", 1),
            ("robotics", 5),  # singleton -> unchanged, not in map
        ])
        self.assertEqual(mapping["foundation-models"], "foundation-model")  # tie -> shorter
        self.assertEqual(mapping["agent"], "agents")  # most-used wins
        self.assertEqual(mapping["policies"], "policy")
        self.assertNotIn("robotics", mapping)
        self.assertNotIn("agents", mapping)  # canonical forms not remapped

    def test_traversal_normalizes_tags_in_db_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PrismDatabase(Path(tmp) / "prism.sqlite3")
            vault = Path(tmp) / "vault"
            notes = NoteService(
                vault, db, Path(tmp) / "archives",
                LLMConfig("https://e", None, None),
                NoteIndexer(Path(tmp) / "lancedb", EmbeddingConfig("https://e", None, None)),
            )
            services = Services(
                settings=None,  # type: ignore[arg-type]
                database=db, indexer=_FakeIndexerOff(), notes=notes, ideas=None,  # type: ignore[arg-type]
            )
            db.insert_note(make_note("n1", tags=("foundation-model", "agents")))
            db.insert_note(make_note("n2", tags=("foundation-models", "agent")))
            db.insert_note(make_note("n3", tags=("agents",)))

            events: list[dict] = []
            summary = run_graph_traversal(services, emit_event=events.append)
            self.assertEqual(summary.notes_retagged, 1)  # only n2 changes
            self.assertGreaterEqual(summary.tags_merged, 2)
            self.assertTrue(any(event["kind"] == "note_retagged" and event["note_id"] == "n2" for event in events))

            self.assertEqual(json.loads(db.find_by_note_id("n2").tags_json), ["foundation-model", "agents"])
            self.assertEqual(json.loads(db.find_by_note_id("n1").tags_json), ["foundation-model", "agents"])
            # Markdown frontmatter rewritten in place.
            md = (vault / "notes" / "n2.md").read_text(encoding="utf-8")
            self.assertIn("foundation-model", md)
            self.assertNotIn("foundation-models", md)


class RelatedRefreshDoesNotPileUpTests(unittest.TestCase):
    def test_auto_links_recomputed_not_accumulated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PrismDatabase(Path(tmp) / "prism.sqlite3")
            # Pre-existing related list: one LLM link (preserved) + one stale auto link (replaced).
            n1 = make_note("aaa", overall=8)
            import dataclasses
            n1 = dataclasses.replace(n1, related_notes_json=json.dumps([
                {"id": "zzz", "title": "LLM pick", "reason": "chosen at creation", "path": "notes/zzz.md"},
                {"id": "old", "title": "stale", "reason": "x", "path": "notes/old.md", "origin": "auto"},
            ]))
            db.insert_note(n1)
            db.insert_note(make_note("bbb", overall=5))
            services = Services(
                settings=None,  # type: ignore[arg-type]
                database=db,
                indexer=type("I", (), {"is_configured": True, "all_vectors": lambda self: {"aaa": [1.0, 0.0], "bbb": [0.98, 0.02]}})(),  # type: ignore[arg-type]
                notes=None,  # type: ignore[arg-type]
                ideas=None,  # type: ignore[arg-type]
            )
            run_graph_traversal(services)
            related = json.loads(db.find_by_note_id("aaa").related_notes_json)
            ids = {item["id"] for item in related}
            self.assertIn("zzz", ids)   # LLM link preserved
            self.assertIn("bbb", ids)   # fresh auto neighbour
            self.assertNotIn("old", ids)  # stale auto link removed (no pile-up)


if __name__ == "__main__":
    unittest.main()

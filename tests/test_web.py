from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from prism.config import Settings
from prism.db import IdeaRecord, NoteRecord, PrismDatabase
from prism.embedding import EmbeddingConfig
from prism.ideas import IdeaService
from prism.index import NoteIndexer
from prism.llm import LLMConfig
from prism.notes import NoteService
from prism.proposals import ProposalService
from prism.web.app import create_app
from prism.web.deps import get_db, get_ideas, get_indexer, get_notes, get_proposals, get_settings


def make_note(note_id: str, *, source_kind="paper", tags=("graph",), related=(), title=None) -> NoteRecord:
    return NoteRecord(
        note_id=note_id,
        source_url=f"https://example.com/{note_id}",
        resolved_url=f"https://example.com/{note_id}",
        note_path=f"notes/{note_id}.md",
        date_saved=f"2026-05-2{len(note_id)}T00:00:00Z",
        status="unreviewed",
        title=title or f"Note {note_id}",
        summary=f"Summary for {note_id}",
        source_kind=source_kind,
        fetch_status="fetched",
        llm_status="generated",
        llm_model="test-model",
        tags_json=json.dumps(list(tags)),
        scores_json=json.dumps({"relevance": 8, "novelty": 7, "overall": 7.5}),
        structured_summary_json=json.dumps(
            {"quick_summary": f"Quick {note_id}", "key_claims": ["claim one", "claim two"]}
        ),
        related_notes_json=json.dumps(
            [{"id": rid, "title": f"Note {rid}", "reason": "related", "path": f"notes/{rid}.md"} for rid in related]
        ),
        embedding_status="indexed",
        embedding_dimensions=768,
    )


def _settings(vault: Path) -> Settings:
    return Settings(
        telegram_bot_token="",
        telegram_allowed_user_ids=frozenset(),
        llm_base_url="https://example.com",
        llm_api_key=None,
        llm_model=None,
        embedding_base_url="https://example.com",
        embedding_api_key=None,
        embedding_model=None,
        vault_path=vault,
        sqlite_path=vault / "x.sqlite3",
        archive_path=vault / "archives",
        lancedb_path=vault / "lancedb",
    )


class WebApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.db = PrismDatabase(root / "prism.sqlite3")
        vault = root / "vault"
        self.vault = vault
        archive = root / "archives"
        llm = LLMConfig("https://example.com", None, None)  # unconfigured
        indexer = NoteIndexer(root / "lancedb", EmbeddingConfig("https://example.com", None, None))  # unconfigured
        notes = NoteService(vault, self.db, archive, llm, indexer)
        ideas = IdeaService(vault, self.db, llm, indexer)

        app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_notes] = lambda: notes
        app.dependency_overrides[get_ideas] = lambda: ideas
        app.dependency_overrides[get_indexer] = lambda: indexer
        app.dependency_overrides[get_proposals] = lambda: ProposalService(self.db, notes)
        app.dependency_overrides[get_settings] = lambda: _settings(vault)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_notes_pagination_and_filters(self) -> None:
        self.db.insert_note(make_note("aaa111", source_kind="paper", tags=["graph", "rag"]))
        self.db.insert_note(make_note("bbb222", source_kind="github", tags=["agents"]))

        all_notes = self.client.get("/api/notes").json()
        self.assertEqual(len(all_notes["items"]), 2)

        page = self.client.get("/api/notes", params={"limit": 1, "offset": 0}).json()
        self.assertEqual(len(page["items"]), 1)

        by_source = self.client.get("/api/notes", params={"source": "github"}).json()
        self.assertEqual([n["id"] for n in by_source["items"]], ["bbb222"])

        by_tag = self.client.get("/api/notes", params={"tag": "graph"}).json()
        self.assertEqual([n["id"] for n in by_tag["items"]], ["aaa111"])

    def test_filter_by_input_source_and_dto(self) -> None:
        import dataclasses

        self.db.insert_note(dataclasses.replace(make_note("aaa111"), input_source="web_ui"))
        self.db.insert_note(dataclasses.replace(make_note("bbb222"), input_source="ai_search"))

        by_input = self.client.get("/api/notes", params={"input_source": "ai_search"}).json()
        self.assertEqual([n["id"] for n in by_input["items"]], ["bbb222"])
        self.assertEqual(by_input["items"][0]["input_source"], "ai_search")

        detail = self.client.get("/api/notes/aaa111").json()
        self.assertEqual(detail["input_source"], "web_ui")

    def test_filter_by_date_and_score(self) -> None:
        import dataclasses

        early = dataclasses.replace(
            make_note("aaa111"), date_saved="2026-01-01T00:00:00Z", scores_json=json.dumps({"overall": 9})
        )
        late = dataclasses.replace(
            make_note("bbb222"), date_saved="2026-12-31T00:00:00Z", scores_json=json.dumps({"overall": 4})
        )
        self.db.insert_note(early)
        self.db.insert_note(late)

        by_min = self.client.get("/api/notes", params={"min_score": 5}).json()
        self.assertEqual([n["id"] for n in by_min["items"]], ["aaa111"])

        by_from = self.client.get("/api/notes", params={"date_from": "2026-06-01"}).json()
        self.assertEqual([n["id"] for n in by_from["items"]], ["bbb222"])

        by_to = self.client.get("/api/notes", params={"date_to": "2026-06-01"}).json()
        self.assertEqual([n["id"] for n in by_to["items"]], ["aaa111"])

        graph = self.client.get("/api/graph", params={"min_score": 5}).json()
        self.assertEqual([n["id"] for n in graph["nodes"]], ["aaa111"])
        self.assertIn("date_saved", graph["nodes"][0])

    def test_token_usage_endpoint(self) -> None:
        empty = self.client.get("/api/usage").json()
        self.assertEqual(empty["total_tokens"], 0)

        self.db.add_token_usage(100, 50, 150)
        self.db.add_token_usage(10, 5, 15)
        usage = self.client.get("/api/usage").json()
        self.assertEqual(usage["total_tokens"], 165)
        self.assertEqual(usage["prompt_tokens"], 110)
        self.assertEqual(usage["calls"], 2)
        self.assertEqual(usage["today_total_tokens"], 165)

    def test_maintenance_settings_round_trip(self) -> None:
        import os

        feeds = Path(self._tmp.name) / "feeds.yaml"
        prev = os.environ.get("PRISM_FEEDS_PATH")
        os.environ["PRISM_FEEDS_PATH"] = str(feeds)
        try:
            defaults = self.client.get("/api/maintenance/settings").json()
            self.assertEqual(defaults["link_threshold"], 0.70)

            saved = self.client.put("/api/maintenance/settings", json={"link_threshold": 0.8, "max_auto_links": 4}).json()
            self.assertEqual(saved["link_threshold"], 0.8)
            self.assertEqual(saved["max_auto_links"], 4)
            self.assertEqual(saved["dup_threshold"], 0.92)  # untouched field preserved

            # Persisted to the YAML and reloaded.
            again = self.client.get("/api/maintenance/settings").json()
            self.assertEqual(again["link_threshold"], 0.8)
            self.assertIn("traversal", feeds.read_text())
        finally:
            if prev is None:
                os.environ.pop("PRISM_FEEDS_PATH", None)
            else:
                os.environ["PRISM_FEEDS_PATH"] = prev

    def test_note_detail_parses_json_columns(self) -> None:
        self.db.insert_note(make_note("aaa111", tags=["graph"], related=["bbb222"]))
        detail = self.client.get("/api/notes/aaa111").json()
        self.assertEqual(detail["scores"]["overall"], 7.5)
        self.assertEqual(detail["tags"], ["graph"])
        self.assertEqual(detail["structured_summary"]["key_claims"], ["claim one", "claim two"])
        self.assertEqual(detail["related_notes"][0]["id"], "bbb222")

        self.assertEqual(self.client.get("/api/notes/missing").status_code, 404)

    def test_graph_dedup_and_dangling(self) -> None:
        # aaa <-> bbb (mutual), and aaa -> zzz (dangling, not inserted)
        self.db.insert_note(make_note("aaa111", related=["bbb222", "zzz999"]))
        self.db.insert_note(make_note("bbb222", source_kind="github", related=["aaa111"]))
        graph = self.client.get("/api/graph").json()
        self.assertEqual(graph["counts"]["notes"], 2)
        self.assertEqual(graph["counts"]["links"], 1)
        self.assertEqual(sorted(graph["edges"][0][k] for k in ("source", "target")), ["aaa111", "bbb222"])
        # the two linked notes form one community; nodes carry topic + community
        self.assertEqual(graph["counts"]["communities"], 1)
        self.assertEqual({n["community"] for n in graph["nodes"]}, {0})
        self.assertTrue(all("topic" in n for n in graph["nodes"]))

    def test_tags_and_stats(self) -> None:
        self.db.insert_note(make_note("aaa111", tags=["graph", "rag"]))
        self.db.insert_note(make_note("bbb222", tags=["graph"]))
        tags = self.client.get("/api/tags").json()["items"]
        self.assertEqual(tags[0], {"tag": "graph", "count": 2})

        stats = self.client.get("/api/stats").json()
        self.assertEqual(stats["notes"]["total"], 2)
        self.assertFalse(stats["index_configured"])

    def test_edit_tags(self) -> None:
        self.db.insert_note(make_note("aaa111", tags=["graph"]))
        resp = self.client.put("/api/notes/aaa111/tags", json={"tags": ["New Tag", "vision"]})
        self.assertEqual(resp.json()["tags"], ["new-tag", "vision"])
        again = self.client.get("/api/notes/aaa111").json()
        self.assertEqual(again["tags"], ["new-tag", "vision"])

    def test_list_notes_status_filter(self) -> None:
        self.db.insert_note(make_note("aaa111"))
        self.db.insert_note(make_note("bbb222"))
        self.client.put("/api/notes/bbb222/status", json={"status": "archived"})
        active = {n["id"] for n in self.client.get("/api/notes").json()["items"]}
        self.assertEqual(active, {"aaa111"})
        all_ids = {n["id"] for n in self.client.get("/api/notes", params={"status": "all"}).json()["items"]}
        self.assertEqual(all_ids, {"aaa111", "bbb222"})
        archived = {n["id"] for n in self.client.get("/api/notes", params={"status": "archived"}).json()["items"]}
        self.assertEqual(archived, {"bbb222"})

    def test_bulk_set_status(self) -> None:
        self.db.insert_note(make_note("aaa111"))
        self.db.insert_note(make_note("bbb222"))
        resp = self.client.put("/api/notes/status", json={"ids": ["aaa111", "bbb222", "missing"], "status": "reviewed"})
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual([r["ok"] for r in results], [True, True, False])
        self.assertEqual(self.client.get("/api/notes/aaa111").json()["status"], "reviewed")
        bad = self.client.put("/api/notes/status", json={"ids": ["aaa111"], "status": "bogus"})
        self.assertEqual(bad.status_code, 400)

    def test_stats_includes_status_counts(self) -> None:
        self.db.insert_note(make_note("aaa111"))
        self.client.put("/api/notes/aaa111/status", json={"status": "reviewed"})
        notes = self.client.get("/api/stats").json()["notes"]
        self.assertEqual(notes["reviewed"], 1)
        self.assertEqual(notes["unreviewed"], 0)

    def test_rename_note(self) -> None:
        self.db.insert_note(make_note("aaa111", title="Old Title"))
        resp = self.client.put("/api/notes/aaa111/title", json={"title": "A Better Title"})
        self.assertEqual(resp.json()["title"], "A Better Title")
        again = self.client.get("/api/notes/aaa111").json()
        self.assertEqual(again["title"], "A Better Title")
        self.assertEqual(self.client.put("/api/notes/missing/title", json={"title": "x"}).status_code, 404)

    def test_set_status(self) -> None:
        self.db.insert_note(make_note("aaa111"))
        resp = self.client.put("/api/notes/aaa111/status", json={"status": "reviewed"})
        self.assertEqual(resp.json()["status"], "reviewed")
        self.assertEqual(self.client.get("/api/notes/aaa111").json()["status"], "reviewed")
        bad = self.client.put("/api/notes/aaa111/status", json={"status": "bogus"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.put("/api/notes/missing/status", json={"status": "reviewed"}).status_code, 404)

    def test_delete_note(self) -> None:
        self.db.insert_note(make_note("aaa111"))
        self.assertTrue(self.client.delete("/api/notes/aaa111").json()["ok"])
        self.assertEqual(self.client.get("/api/notes/aaa111").status_code, 404)
        self.assertEqual(self.client.delete("/api/notes/aaa111").status_code, 404)

    def test_idea_rating(self) -> None:
        self.db.insert_idea(
            IdeaRecord(idea_id="idea01", created_at="2026-05-29T00:00:00Z", title="Test Idea", summary="A pitch")
        )
        rated = self.client.post("/api/ideas/idea01/rating", json={"rating": 4}).json()
        self.assertEqual(rated["rating"], 4)
        self.assertEqual(self.client.get("/api/ideas/idea01").json()["rating"], 4)
        self.assertEqual(self.client.post("/api/ideas/missing/rating", json={"rating": 3}).status_code, 404)

    def test_proposals_list_approve_reject(self) -> None:
        import json as _json

        from prism.db import ProposalRecord

        self.db.insert_note(make_note("aaa111"))
        self.db.insert_note(make_note("bbb222"))
        self.db.insert_proposal(ProposalRecord(
            proposal_id="prop01", created_at="2026-05-30T00:00:00Z", kind="merge",
            note_ids_json=_json.dumps(["aaa111", "bbb222"]),
            payload_json=_json.dumps({"keep": "aaa111", "remove": "bbb222", "similarity": 0.97}),
        ))

        listing = self.client.get("/api/proposals").json()
        self.assertEqual(listing["pending"], 1)
        self.assertEqual(listing["items"][0]["id"], "prop01")
        self.assertIn("Merge", listing["items"][0]["description"])

        approved = self.client.post("/api/proposals/prop01/approve").json()
        self.assertTrue(approved["ok"])
        self.assertEqual(approved["proposal"]["status"], "approved")
        # Approving the merge removed the duplicate note.
        self.assertEqual(self.client.get("/api/notes/bbb222").status_code, 404)
        self.assertEqual(self.client.get("/api/proposals").json()["pending"], 0)

        self.assertEqual(self.client.post("/api/proposals/missing/approve").status_code, 404)

    def test_proposal_reject(self) -> None:
        import json as _json

        from prism.db import ProposalRecord

        self.db.insert_note(make_note("aaa111"))
        self.db.insert_note(make_note("bbb222"))
        self.db.insert_proposal(ProposalRecord(
            proposal_id="prop02", created_at="2026-05-30T00:00:00Z", kind="merge",
            note_ids_json=_json.dumps(["aaa111", "bbb222"]),
            payload_json=_json.dumps({"keep": "aaa111", "remove": "bbb222"}),
        ))
        rejected = self.client.post("/api/proposals/prop02/reject").json()
        self.assertTrue(rejected["ok"])
        self.assertEqual(rejected["proposal"]["status"], "rejected")
        self.assertIsNotNone(self.client.get("/api/notes/bbb222").json())

    def test_maintenance_ingest_no_feeds(self) -> None:
        import os
        from unittest.mock import patch

        # Point at a path that doesn't exist so no feeds load.
        with patch.dict(os.environ, {"PRISM_FEEDS_PATH": str(self.vault / "nope.yaml")}):
            res = self.client.post("/api/maintenance/ingest").json()
        self.assertTrue(res["ok"])
        self.assertEqual(res["feeds_configured"], 0)
        self.assertEqual(res["created"], 0)

    def test_maintenance_traverse_normalizes_tags(self) -> None:
        # Indexer unconfigured -> traversal does tag normalization only.
        self.db.insert_note(make_note("aaa111", tags=["foundation-model"]))
        self.db.insert_note(make_note("bbb222", tags=["foundation-models"]))
        res = self.client.post("/api/maintenance/traverse").json()
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["tags_merged"], 1)
        self.assertGreaterEqual(res["notes_retagged"], 1)

    def test_ask_graceful_when_unconfigured(self) -> None:
        result = self.client.post("/api/ask", json={"question": "what is rag?"}).json()
        self.assertFalse(result["ok"])
        self.assertIn("not configured", result["message"].lower())

    def test_generate_idea_graceful_when_unconfigured(self) -> None:
        result = self.client.post("/api/ideas", json={"topic": "robots"}).json()
        self.assertFalse(result["ok"])
        self.assertIn("llm", result["message"].lower())

    def test_find_reports_unconfigured(self) -> None:
        result = self.client.get("/api/find", params={"q": "graph"}).json()
        self.assertFalse(result["configured"])
        self.assertEqual(result["results"], [])

    def test_tree_nests_and_maps_note_ids(self) -> None:
        self.db.insert_note(make_note("aaa111"))  # note_path = notes/aaa111.md
        (self.vault / "notes").mkdir(parents=True, exist_ok=True)
        (self.vault / "notes" / "aaa111.md").write_text("# note", encoding="utf-8")
        (self.vault / "notes" / "orphan.md").write_text("# orphan", encoding="utf-8")
        (self.vault / ".git").mkdir(exist_ok=True)
        (self.vault / ".git" / "HEAD").write_text("ref", encoding="utf-8")

        tree = self.client.get("/api/tree").json()
        self.assertEqual(tree["type"], "dir")
        names = {c["name"]: c for c in tree["children"]}
        self.assertIn("notes", names)
        self.assertNotIn(".git", names)  # hidden dirs skipped

        files = {f["name"]: f for f in names["notes"]["children"]}
        self.assertEqual(files["aaa111.md"]["note_id"], "aaa111")
        self.assertIsNone(files["orphan.md"]["note_id"])

    def test_tree_includes_archive_root(self) -> None:
        self.db.insert_note(make_note("aaa111", title="My Paper"))
        arc = self.vault / "archives" / "aaa111"
        arc.mkdir(parents=True, exist_ok=True)
        (arc / "source.pdf").write_text("%PDF-1.4", encoding="utf-8")

        tree = self.client.get("/api/tree").json()
        archive = next(c for c in tree["children"] if c["name"] == "Archive")
        folder = archive["children"][0]
        self.assertEqual(folder["name"], "My Paper")  # labeled by note title
        self.assertEqual(folder["path"], "aaa111")
        pdf = folder["children"][0]
        self.assertEqual(pdf["name"], "source.pdf")
        self.assertEqual(pdf["root"], "archive")

    def test_file_serves_and_blocks_traversal(self) -> None:
        (self.vault / "notes").mkdir(parents=True, exist_ok=True)
        (self.vault / "notes" / "aaa111.md").write_text("# hello", encoding="utf-8")

        ok = self.client.get("/api/file", params={"root": "vault", "path": "notes/aaa111.md"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.text, "# hello")

        self.assertEqual(self.client.get("/api/file", params={"root": "vault", "path": "../secrets"}).status_code, 400)
        self.assertEqual(self.client.get("/api/file", params={"root": "vault", "path": "notes/missing.md"}).status_code, 404)
        self.assertEqual(self.client.get("/api/file", params={"root": "nope", "path": "x"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()

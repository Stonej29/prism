# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Run all tests:
```sh
PYTHONPATH=src python -m unittest discover -s tests
```

Run a single test file:
```sh
PYTHONPATH=src python -m unittest tests.test_phase4
```

Syntax check all source and tests:
```sh
python -m compileall src tests
```

Build and run the bot via Docker:
```sh
docker compose build
sudo docker compose up -d --force-recreate
sudo docker compose logs -f prism
```

Run the web UI (FastAPI + React three-pane "Atlas" interface) via Docker:
```sh
docker compose build prism-web
sudo docker compose up -d prism-web   # serves on http://localhost:5890
```

Develop the web UI locally (FastAPI on :5890, Vite dev server on :5173 proxying /api):
```sh
# Terminal 1 — API (shares runtime/ with the bot)
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb \
  VAULT_PATH=runtime/research-vault ARCHIVE_PATH=runtime/archives \
  PRISM_WEB_RELOAD=1 python -m prism.web
# Terminal 2 — frontend
cd frontend && npm install && npm run dev
```

Build the frontend bundle (type-checked):
```sh
cd frontend && npm run build   # outputs frontend/dist, served by FastAPI in prod
```

Run the terminal UI (full-screen Textual three-pane interface) or the scriptable CLI — both share the same `runtime/`:
```sh
# Full-screen TUI
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb \
  VAULT_PATH=runtime/research-vault ARCHIVE_PATH=runtime/archives \
  PRISM_FEEDS_PATH=runtime/feeds.yaml python -m prism.tui
# Scriptable CLI (same env vars); maps 1:1 to bot commands
PYTHONPATH=src ... python -m prism.cli recent
PYTHONPATH=src ... python -m prism.cli find "state space models"
PYTHONPATH=src ... python -m prism.cli status
```

Run the background worker (scheduled feed ingestion + graph maintenance) via Docker:
```sh
docker compose build prism-worker
sudo docker compose up -d prism-worker
```

Run a worker job once (manual / debugging):
```sh
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb \
  VAULT_PATH=runtime/research-vault ARCHIVE_PATH=runtime/archives \
  PRISM_FEEDS_PATH=runtime/feeds.yaml python -m prism.worker ingest   # pull feeds once
# Or inside Docker:
docker compose run --rm prism-worker python -m prism.worker ingest
```

Inspect graph-maintenance proposals:
```sh
sqlite3 runtime/prism.sqlite3 "select proposal_id,kind,status,note_ids_json from proposals order by created_at desc limit 10;"
```

Rebuild the LanceDB semantic index from SQLite:
```sh
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb python -m prism.index rebuild
# Or inside Docker:
docker compose run --rm prism python -m prism.index rebuild
```

Inspect note processing status:
```sh
sqlite3 runtime/prism.sqlite3 "select note_id,title,llm_status,embedding_status,embedding_error,embedding_model,embedding_dimensions from notes order by date_saved desc limit 10;"
```

Inspect generated ideas and ratings:
```sh
sqlite3 runtime/prism.sqlite3 "select idea_id,title,rating,llm_status from ideas order by created_at desc limit 10;"
```

## Architecture

PRISM is a Telegram bot that saves URLs into an Obsidian-compatible Markdown vault. The full pipeline for each URL is:

1. **Fetch** (`fetch.py`) — detects source kind (arxiv paper, GitHub repo, PDF, or general website) and archives raw content under `runtime/archives/<note_id>/`. Each archive dir contains `extracted.txt`, `metadata.json`, and the raw source (`raw.html`, `source.pdf`, or `readme.md`).

2. **LLM** (`llm.py`) — two passes against an OpenAI-compatible chat endpoint, orchestrated by `NoteService._apply_llm`. **Call 1 (ground truth, `generate_note`)** sends only the extracted text (no profile) and returns the profile-independent fields: title, quick/detailed summary, key claims, limitations, technical details, tags, related notes, and the `novelty`/`credibility` scores. **Call 2 (personalization, `personalize_note`)** sends that ground truth **+ the personal profile** (`vault/profile/personal.md`) but *not* the source text, and returns the reader-specific fields: `why_it_matters`, `personal_relevance`, `project_ideas`, and the `relevance`/`actionability`/`interest`/`overall` scores. Both are merged into one `structured_summary_json`/`scores_json` (no schema split). Because call 2 omits the source and never touches tags/related/summaries/embedding, it is cheap to re-run when the profile changes: `NoteService.repersonalize(id)` (on-demand, surfaced as `/repersonalize`, CLI `repersonalize`, TUI verb, `POST /api/notes/{id}/repersonalize`) and `repersonalize_all()` (bulk, auto-run after every `/reset_me`/`/update_me` profile edit). The field split lives in `PERSONAL_PROSE_FIELDS` / `PERSONAL_SCORE_FIELDS` / `GROUND_TRUTH_CONTEXT_FIELDS` in `notes.py`.

3. **Embedding + Indexing** (`embedding.py`, `index.py`) — embeds the canonical index text (title + summary + tags) via an OpenAI-compatible embeddings endpoint and upserts it into LanceDB. Used for `/related` semantic search and to supply related candidates to the LLM before generation.

4. **NoteService** (`notes.py`) — orchestrates the above steps, writes the Markdown note to `vault/notes/`, and persists metadata to SQLite.

5. **Database** (`db.py`) — SQLite tables `notes` (all note metadata), `ideas` (generated ideas + ratings), and `proposals` (graph-maintenance suggestions for human review). Schemas evolve by `ALTER TABLE ADD COLUMN` via `_add_missing_columns()` / `_add_missing_idea_columns()` / `_add_missing_proposal_columns()` at startup, so old databases are automatically migrated without data loss. Notes carry both `source_kind` (what the content is: paper/github/huggingface/youtube/pdf/website) and `input_source` (how it entered PRISM: telegram/web_ui/ai_search/scheduled).

6. **Idea engine** (`ideas.py`) — `IdeaService` synthesizes a project idea from the saved knowledge base (semantic search on a topic, else recent generated notes) plus the personal profile and previously rated ideas. Writes an idea Markdown note to `vault/generated-ideas/`, persists an `IdeaRecord` to SQLite, and supports a human 1–5 rating loop that rewrites the note's `rating` frontmatter and feeds future idea prompts.

7. **Bot** (`bot.py`) — wires the pipeline to Telegram handlers. Commands: `/start`, `/help`, `/more <id>`, `/rename <id> <title>`, `/status_set <id> <status>`, `/reprocess <id>`, `/reprocess_all`, `/repersonalize <id>`, `/retry_failed [n]`, `/delete <id>`, `/wipe_all`, `/related <query-or-note_id>`, `/status`, `/recent`, `/inbox`, `/tags [tag]`, `/find <query>`, `/ask <question>`, `/idea [topic]`, `/ideas`, `/proposals`, `/ingest`, `/traverse`, `/reset_me <text>`, `/update_me <text>`. `/ingest` and `/traverse` trigger the worker's feed-ingestion and graph-maintenance jobs on demand from inside the bot process (reusing `run_feed_ingestion` / `run_graph_traversal`); the web UI exposes the same via `POST /api/maintenance/{ingest,traverse}` and buttons in the proposals panel. `/ask` answers questions grounded only in saved notes (semantic retrieval → LLM, no live web search). The command list is registered with Telegram's command menu via `set_my_commands` in `_post_init` (sourced from the `COMMANDS` list, which also generates `/help`). Inline-button callbacks are handled by `CallbackQueryHandler`s: idea ratings (`idearate:<idea_id>:<n>`) and list pagination (`pg:<kind>:<offset>[:<tag>]`). The DB-backed browse commands (`/recent`, `/ideas`, `/tags`) paginate `PAGE_SIZE` items per page with ◀/▶ buttons via `_page_view`, backed by `offset` params on the `list_*` DB methods.

8. **Worker** (`worker/`) — a separate `prism-worker` process/container (APScheduler) sharing the same `runtime/` and the `prism.services.build_services` factory used by the bot and web app. Cron jobs are configured by `runtime/feeds.yaml` (`PRISM_FEEDS_PATH`), with schedules interpreted in `schedule.timezone` (default `Europe/Copenhagen`, DST-aware via `tzdata`):
   - **Feed ingestion** (`worker/ingest.py` + `worker/feeds.py`) — each item URL pushed through `NoteService.save_url(url, input_source="ai_search")`; dedup handled by the normal pipeline. Default daily 07:00. Two feed types: `rss` (save each entry's own link) and `digest` (for roundup newsletters where one post covers many items — opens the newest `posts` entries and follows their **"Read more"** anchors via `fetch.extract_read_more_links`, saving each underlying repo/paper/project page as its own note rather than the digest post).
   - **Graph traversal** (`worker/traversal.py`, opt-in via `traversal_enabled`, default weekly Monday 05:00) — *additive auto-apply + proposals*. Auto (no approval): **recomputes** each note's automatic `related_notes` from semantic neighbours (cosine over `indexer.all_vectors()`) each run — links carry `origin:"auto"` so they are refreshed rather than accumulated, while LLM-chosen links from note creation are preserved; and **normalizes near-duplicate tags** corpus-wide (`build_canonical_tag_map` groups by a de-pluralized/separator-stripped key, e.g. `foundation-model`/`foundation-models`, rewriting via `NoteService.apply_tags`). Proposals only: near-duplicate **note merges** written to the `proposals` table.
   - **Backup** (`worker/backup.py`, opt-in via `backup_enabled`, default daily 02:00) — `git add -A` + commit in the vault repo (local only, no push; no-op on a clean tree) and a timestamped SQLite snapshot under `<sqlite_dir>/backups/`, pruned to the most recent 14. Best-effort: a missing repo / clean tree / copy error is recorded in `BackupSummary.errors`, never raised.
   - **Re-embed** (`worker/reembed.py`, opt-in via `reembed_enabled`, default weekly Sunday 03:00) — recomputes `hash_text(canonical_index_text(record))` for every note and re-embeds only those whose stored `embedding_text_hash` no longer matches (cheaper than a full `python -m prism.index rebuild`). No-op when embeddings are unconfigured.
   - Proposals are reviewed/approved via `ProposalService` (`proposals.py`), surfaced in the bot (`/proposals` + `prop:approve|reject:<id>` callbacks) and the web UI (`/api/proposals`, Atlas review overlay). Approving a `merge` calls `NoteService.merge_notes(keep, remove)`: when the LLM is configured it **synthesizes one consolidated note** from both sources (via `LLMClient.merge_notes`, regenerating the kept note's content and losing nothing from either), otherwise it does a structural merge; either way tags and related-links are unioned, inbound backlinks are re-pointed `remove→keep` (no dangling refs), the kept note is re-embedded, and the duplicate is deleted. Run jobs once with `python -m prism.worker {ingest,backup,reembed}` (also `CliCore.{reembed,backup}` → `prism-cli {reembed,backup}`).

### Data flow
```
Telegram message → handle_message → NoteService.save_url
  → fetch_source (fetch.py)        → runtime/archives/<id>/
  → _apply_llm (llm.py)            → structured JSON fields on NoteRecord
  → render_note (notes.py)         → runtime/research-vault/notes/<date>-<slug>.md
  → database.insert_note (db.py)   → runtime/prism.sqlite3
  → _index_after_persist (index.py)→ runtime/lancedb/
```

### Key design decisions

- **NoteRecord is immutable** (`frozen=True` dataclass). Updates are made via `dataclasses.replace()` and then persisted with `database.update_note()`. In-place edits follow `NoteService.apply_tags`'s pattern (`replace` → `update_note` → `_render_to_disk`): `rename_note` also re-embeds (the title leads `canonical_index_text`), `set_status` does not (status isn't embedded; valid values in `NOTE_STATUSES` = unreviewed/reviewed/archived). Both are surfaced through `CliCore.{rename_note,set_status}` (returning `EditResult`) to the bot (`/rename`, `/status_set`), CLI (`rename`, `set-status`), TUI, and web (`PUT /api/notes/{id}/{title,status}`). Bulk status: `CliCore.set_status_bulk`, CLI `set-status <status> <id…>`, web `PUT /api/notes/status`.
- **Review-status filtering**: the `list_notes_*` DB methods take an optional `status` (`db._status_clause`: `None` → hide `archived` from the default view, `"all"` → no filter, else exact match). `get_note_stats`/`NoteStats` carry `unreviewed`/`reviewed`/`archived` counts. The bot's `/inbox` (and TUI `inbox` / `f` filter cycle, CLI `--status`) surface the unreviewed queue; the web graph keeps the full corpus (`gather_all_notes` uses `status="all"`) and dims archived nodes, with an inbox badge in the TopBar.
- **Hybrid search**: `NoteService.search()` blends semantic (`indexer.search_text`, when configured) with `database.search_notes_keyword` via `_merge_candidates`, degrading to keyword-only when embeddings are unconfigured or semantic fails — so `/find` always works. `/ask` reuses it for candidate gathering. (`/related` stays semantic-only.)
- **All failures are non-blocking**: fetch failure, LLM failure, or embedding failure each produce a degraded note rather than an exception that loses the capture. Status fields (`fetch_status`, `llm_status`, `embedding_status`) track which steps succeeded.
- **Deduplication**: checked by exact `source_url` first, then by `content_hash` of the extracted text. A duplicate returns the existing record without creating a new note.
- **LanceDB is a cache**: SQLite and Markdown files are the source of truth. The index can be fully rebuilt from SQLite at any time via `python -m prism.index rebuild`.
- **LLM provider compatibility**: falls back to a request without `response_format` if the provider returns HTTP 400.
- **HTTP robustness**: `LLMClient._post` and `EmbeddingClient._post` retry transient failures (timeouts, connection resets, 5xx) with bounded exponential backoff (`RETRY_ATTEMPTS`/`RETRY_BACKOFF_BASE`); 4xx is never retried so the 400 `response_format` fallback path is preserved. Both log token `usage` (prompt/completion/total) at INFO on success.

### Web UI (`src/prism/web/` + `frontend/`)

A separate FastAPI service (entry point `prism-web` / `python -m prism.web`) puts a REST API in front of the same service layer the bot uses, and serves a React/Vite three-pane "Atlas" interface (directory tree · force-directed note graph · note detail). It is a **distinct process/container** (`prism-web` in `compose.yaml`) sharing the same `runtime/` volume; the Telegram bot is untouched.

- `web/deps.py` builds the service singletons (`PrismDatabase`, `NoteIndexer`, `NoteService`, `IdeaService`) lazily, mirroring `PrismBot.__init__`, and exposes them as FastAPI `Depends` providers (overridable in tests via `app.dependency_overrides`). `load_settings(require_telegram=False)` lets the web app boot without a Telegram token.
- Route handlers are plain `def` (not `async def`) so blocking/LLM service calls run in FastAPI's threadpool. `PrismDatabase.connect()` opens a fresh connection per call, so the singleton is thread-safe.
- `web/serializers.py` turns frozen `NoteRecord`/`IdeaRecord` dataclasses into JSON DTOs by **reusing** the helpers in `notes.py` (`scores_for_record`, `tags_for_record`, `structured_summary`, `related_notes_for_record`) — never re-parsing the `*_json` columns by hand.
- `web/graph.py` builds the graph payload: nodes = notes, edges = deduped undirected pairs from each note's `related_notes_json` (dangling refs dropped), clusters = `source_kind`.
- Endpoints live under `/api` (`web/routes/`): notes (list[+status filter]/detail/save/reprocess/reprocess-all/repersonalize/retry/delete/edit-tags/rename/set-status/bulk-status), graph, tags, stats, find, ask, ideas (list/generate/rate/delete). In production `app.py` mounts the built `frontend/dist` as a SPA at `/` (via `PRISM_WEB_STATIC`, default `/app/static` in Docker).
- API tests: `tests/test_web.py` (FastAPI `TestClient` against a seeded temp DB with unconfigured LLM/indexer).

### Terminal UI + CLI (`src/prism/tui/`, `src/prism/cli/`, `src/prism/cli_core.py`)

Two more front-ends over the same service layer, sharing the same `runtime/` (the bot/web/worker are untouched).

- `cli_core.py` — a synchronous, UI-agnostic `CliCore` facade that **both** the TUI and CLI call, so orchestration lives in one place. `CliCore.from_settings(load_settings(require_telegram=False))` builds the shared `Services` and a `ProposalService(database, notes)` alongside it. It owns the bits the bot did inline: the `related` query-vs-note-id branch, feed loading for `ingest` (`load_worker_config` → `run_feed_ingestion`), `traverse` (`run_graph_traversal`), and capability gates (`search_ready`/`llm_ready`). Methods return the existing frozen result types (`SaveResult`, `AskResult`, `IngestionSummary`, …) plus small wrappers (`SearchResult`, `IngestResult`, `StatusInfo`). It never imports Textual/argparse. Tested in `tests/test_cli_core.py`.
- `tui/` — a **Textual** app (`prism-tui` / `python -m prism.tui`). `AtlasScreen` is a three-pane layout: a mode-switchable sidebar (`SourceList`: notes/ideas/tags/proposals) · a Markdown `DetailPane` · a `CommandBar`. **All blocking service calls run on `@work(thread=True)` workers** via the generic `_run` helper, which catches exceptions and posts a typed `WorkerResult` (or `ListResult`) back to the UI thread — the event loop never blocks. Rendering reuses the `notes.py` helpers (`render.py`), never re-parsing `*_json`. Destructive actions use modal screens (`ConfirmScreen`, typed-code `WipeConfirmScreen`, `RatingScreen`). `tui/commands.py` is the single command vocabulary, mirroring the bot's `COMMANDS` 1:1 (plus `save`); `tests/test_tui.py` includes a **parity test** that fails if a future bot command isn't reachable in the TUI, plus `App.run_test()`/`Pilot` tests. `styles.tcss` is shipped via `[tool.setuptools.package-data]`.
- `cli/` — a thin argparse front-end (`prism-cli` / `python -m prism.cli`) over the same `CliCore`; subcommands map 1:1 to facade methods with plain-text output for piping. `wipe-all` requires `--yes`.

## Environment

Copy `.env.example` to `.env`. Required:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS` — comma-separated numeric Telegram user IDs

Optional (each service degrades gracefully if unset):
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` — LLM note generation (default base URL: OpenRouter)
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` — semantic indexing (default base URL: OpenAI)

Web UI only (the bot ignores these; `prism-web` does not require the Telegram vars):
- `PRISM_WEB_HOST` (default `127.0.0.1`) / `PRISM_WEB_PORT` (default `5890`) / `PRISM_WEB_RELOAD` (`1` for uvicorn auto-reload) / `PRISM_WEB_STATIC` (path to the built `frontend/dist`; default `/app/static` in Docker)

Runtime data lives in `runtime/` (Docker volume mount) and is intentionally excluded from this repo. The Obsidian vault at `runtime/research-vault` is its own separate git repo.

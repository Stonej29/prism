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

## Architecture

PRISM is a Telegram bot that saves URLs into an Obsidian-compatible Markdown vault. The full pipeline for each URL is:

1. **Fetch** (`fetch.py`) — detects source kind (arxiv paper, GitHub repo, PDF, or general website) and archives raw content under `runtime/archives/<note_id>/`. Each archive dir contains `extracted.txt`, `metadata.json`, and the raw source (`raw.html`, `source.pdf`, or `readme.md`).

2. **LLM** (`llm.py`) — sends extracted text plus a personal profile (`vault/profile/personal.md`) to an OpenAI-compatible chat endpoint. Returns structured JSON with title, quick summary, detailed summary, key claims, limitations, tags, numeric scores (1–10), and related note references.

3. **Embedding + Indexing** (`embedding.py`, `index.py`) — embeds the canonical index text (title + summary + tags) via an OpenAI-compatible embeddings endpoint and upserts it into LanceDB. Used for `/related` semantic search and to supply related candidates to the LLM before generation.

4. **NoteService** (`notes.py`) — orchestrates the above steps, writes the Markdown note to `vault/notes/`, and persists metadata to SQLite.

5. **Database** (`db.py`) — single SQLite table `notes` with all metadata. Schema evolves by `ALTER TABLE ADD COLUMN` via `_add_missing_columns()` at startup, so old databases are automatically migrated without data loss.

6. **Bot** (`bot.py`) — wires the pipeline to Telegram handlers. Commands: `/start`, `/more <id>`, `/reprocess <id>`, `/related <query-or-note_id>`.

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

- **NoteRecord is immutable** (`frozen=True` dataclass). Updates are made via `dataclasses.replace()` and then persisted with `database.update_note()`.
- **All failures are non-blocking**: fetch failure, LLM failure, or embedding failure each produce a degraded note rather than an exception that loses the capture. Status fields (`fetch_status`, `llm_status`, `embedding_status`) track which steps succeeded.
- **Deduplication**: checked by exact `source_url` first, then by `content_hash` of the extracted text. A duplicate returns the existing record without creating a new note.
- **LanceDB is a cache**: SQLite and Markdown files are the source of truth. The index can be fully rebuilt from SQLite at any time via `python -m prism.index rebuild`.
- **LLM provider compatibility**: falls back to a request without `response_format` if the provider returns HTTP 400.

## Environment

Copy `.env.example` to `.env`. Required:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS` — comma-separated numeric Telegram user IDs

Optional (each service degrades gracefully if unset):
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` — LLM note generation (default base URL: OpenRouter)
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` — semantic indexing (default base URL: OpenAI)

Runtime data lives in `runtime/` (Docker volume mount) and is intentionally excluded from this repo. The Obsidian vault at `runtime/research-vault` is its own separate git repo.

# PRISM Implementation Status

Last updated: 2026-05-29

## Current State

PRISM is a Docker Compose Telegram bot that saves links into an Obsidian-compatible vault, archives source material, extracts text, deduplicates captures, optionally generates structured LLM notes, and can build a LanceDB semantic index for related-note search and Obsidian backlinks.

## Completed

### Phase 1: Basic Skeleton

- Python package and Docker setup are in place.
- Telegram bot accepts plain URL messages.
- Short note IDs are generated for Telegram commands.
- Markdown notes are written to `research-vault/notes/`.
- SQLite stores note metadata and processing state.

### Phase 2: Fetching, Archiving, Extraction

- Supports general websites, PDFs, arXiv papers, and GitHub repo READMEs.
- Archives raw HTML, PDFs, README files, extracted text, and metadata JSON under `runtime/archives/<note_id>/`.
- Computes content hashes and deduplicates by exact URL and content hash.
- Website extraction uses trafilatura plus fallback HTML parsing.
- Same-site iframe extraction is implemented for wrapper pages, including NVIDIA SIL-style `shared/index.html?target=...` pages that load `main.html` content.
- `/reprocess <id>` can repair old website archives where `extracted.txt` was empty but `raw.html` exists.

### Phase 3: LLM Note Generation

- OpenAI-compatible chat client added in `src/prism/llm.py`.
- Config comes from `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`.
- Source text sent to the LLM is capped at 60,000 characters.
- LLM output is expected as structured JSON and rendered into a detailed Obsidian note.
- Provider `response_format` rejection via HTTP 400 retries once without `response_format`.
- Missing LLM config, empty extracted text, timeouts, provider errors, or malformed JSON do not block note creation.
- SQLite has LLM status, error, generated timestamp, model, tags, scores, and structured summary columns.
- Personal profile is created at `vault/profile/personal.md` if missing.
- Telegram replies include generated summary and tags on success, or compact archive/LLM failure status otherwise.
- `/more <id>` shows the structured detailed summary when available.
- `/reprocess <id>` reruns LLM generation from archived extracted text and rewrites the note.

### Phase 4: LanceDB Semantic Search and Linking

- OpenAI-compatible embedding client added in `src/prism/embedding.py`.
- Config comes from `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`, and `LANCEDB_PATH`.
- LanceDB dependency and indexing subsystem added in `src/prism/index.py`.
- SQLite now tracks embedding status, errors, timestamps, model, dimensions, text hash, and related-note JSON.
- Notes are indexed best-effort after successful save and `/reprocess`; embedding or LanceDB failures do not block archiving, note rendering, or SQLite persistence.
- Manual reindex command added: `PYTHONPATH=src python -m prism.index rebuild`.
- Related candidates are retrieved before LLM note generation and passed into the LLM context.
- LLM output supports normalized `related_notes` with `{id, title, reason}`.
- Generated notes render `related_notes` frontmatter and a `## Related Notes` section with Obsidian wiki links.
- Telegram `/related <query-or-note_id>` returns top semantic matches with `/more <id>` shortcuts.

## Verified

Automated checks currently pass:

```sh
python -m compileall src tests
PYTHONPATH=src python -m unittest discover -s tests
```

Current unit suite: 36 tests. Four `/related` bot tests are skipped in the host Python environment when `python-telegram-bot` is not installed; the Docker image installs it.

Docker build has also been verified:

```sh
docker compose build
```

Manual checks still recommended for Phase 4:

- Set `EMBEDDING_API_KEY` and `EMBEDDING_MODEL`.
- Rebuild/recreate the container.
- Run the reindex CLI.
- On SELinux hosts, Compose uses a shared `:z` label so `docker compose run` reindex jobs and the live bot can both access `runtime/`.
- Send `/related robotics` in Telegram.
- Save a new related paper/page and confirm `## Related Notes` backlinks appear in the generated Markdown.

## Known Limitations

- Full JavaScript/browser rendering is not implemented. The iframe fallback fixes some static iframe-shell pages, but arbitrary JS-heavy sites may still extract poorly.
- LanceDB is an index/cache; SQLite and Markdown remain the source of truth.
- No background queue or scheduled indexing; indexing runs synchronously and best-effort after save/reprocess or manually through the rebuild CLI.
- `/ask`, `/recent`, `/tags`, `/idea`, and idea ratings are not implemented.
- GitHub support fetches README metadata/content only; it does not clone or inspect repo structure.
- LLM generation and embedding/indexing are synchronous in the Telegram request path, so slow providers can delay replies.
- LLM or embedding provider rate limits surface in SQLite as failed statuses; use `/reprocess <id>` or the rebuild CLI to retry.

## Next Recommended Phase

### Phase 5: Operational Hardening and Retrieval UX

Suggested implementation order:

1. Add background jobs for slow LLM and embedding work.
2. Add `/recent`, `/tags`, and richer `/related` result pagination.
3. Add `/ask` retrieval over indexed notes.
4. Add index health/status commands.
5. Improve README runtime docs for Phase 3 and Phase 4 configuration.
6. Add optional local embedding backend support if direct API costs or reliability become an issue.

## Useful Commands

Run tests:

```sh
PYTHONPATH=src python -m unittest discover -s tests
```

Build container:

```sh
docker compose build
```

Run bot:

```sh
sudo docker compose up -d --force-recreate
sudo docker compose logs -f prism
```

Rebuild semantic index from known SQLite notes:

```sh
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb python -m prism.index rebuild
```

If using Docker instead of host Python:

```sh
docker compose run --rm prism python -m prism.index rebuild
```

Inspect recent LLM and embedding status:

```sh
sqlite3 runtime/prism.sqlite3 "select note_id,title,llm_status,embedding_status,embedding_error,embedding_model,embedding_dimensions from notes order by date_saved desc limit 10;"
```

Reprocess a note from Telegram:

```text
/reprocess <note_id>
```

Search related notes from Telegram:

```text
/related robotics
/related <note_id>
```

# PRISM Implementation Status

Last updated: 2026-05-29

## Current State

PRISM is a Docker Compose Telegram bot that saves links into an Obsidian-compatible vault, archives source material, extracts text, deduplicates captures, optionally generates structured LLM notes, builds a LanceDB semantic index for related-note search and Obsidian backlinks, exposes retrieval/browse and maintenance commands from Telegram, and can synthesize and rate new project ideas from the saved knowledge base.

## Scope

The full MVP scope is implemented across Phases 1–6.

- **MVP complete:** Telegram bot, default link saving, website/PDF/GitHub fetching, cleaned-text + raw-HTML snapshots, structured Markdown note generation, Obsidian vault + YAML frontmatter, tags, related notes, personal profile, evaluation scores, SQLite metadata, LanceDB semantic search, duplicate detection, `/ask`, `/more`, `/recent`, `/tags`, `/related`, `/idea`, idea Markdown files, and 1–5 star idea ratings.
- **Beyond MVP:** `/reprocess`, arXiv metadata, and GitHub repo metadata (stars/license/language) are implemented. `/find`, `/status`, `/retry_failed`, `/delete`, `/wipe_all`, `/reset_me`, `/update_me`, and `/help` are extra commands beyond the original scope.
- **Not implemented:** live web search in `/ask` is intentionally excluded. Scheduled daily/weekly ideas remain future work.

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

### Phase 5: Background Processing and Retrieval Commands

- Slow `save_url` and `reprocess` work runs in background asyncio tasks so Telegram acks immediately.
- `/recent` browses recent notes and `/tags [tag]` browses tag counts or notes for a tag, both paginated with inline ◀/▶ buttons (`/ideas` too).
- `/find <query>` runs background semantic search; `/status` reports note/LLM/embedding counts and index state.
- `/retry_failed [n]` retries failed LLM generation or embedding/indexing work in a background task.
- `/delete <id>` deletes a note or generated idea after an inline yes/no confirmation.
- `/wipe_all` requires a random confirmation code before deleting saved notes, generated ideas, archives, and the semantic index cache.
- `/reset_me <text>` and `/update_me <text>` rewrite or extend the personal profile through the configured LLM.
- `/help` lists all commands, and the command list is registered with Telegram's command menu via `set_my_commands`; both are generated from a single `COMMANDS` table in `bot.py`.

### Phase 6: Idea Generation and Ratings

- `IdeaService` (`src/prism/ideas.py`) synthesizes a project idea from the saved knowledge base, the personal profile, and previously rated ideas.
- `/idea [topic]` does a semantic search for the topic (or draws from recent generated notes when no topic is given) and generates a structured idea in a background task.
- Ideas are saved as Markdown in `vault/generated-ideas/` and persisted to a new SQLite `ideas` table (migrated via `_add_missing_idea_columns()`).
- The `/idea` reply carries inline ★1–★5 buttons; a `CallbackQueryHandler` persists the rating to SQLite and rewrites the idea note's `rating` frontmatter.
- High-rated past ideas are fed into future idea prompts to steer generation toward preferred directions.
- `/ideas` browses recent generated ideas with their ratings (paginated with inline ◀/▶ buttons).
- LLM failures produce a degraded idea note (`llm_status="failed"`) rather than blocking, consistent with the rest of the pipeline.

### `/ask`: Retrieval-augmented Q&A

- `NoteService.ask()` (`src/prism/notes.py`) embeds the question, semantic-searches LanceDB, grounds the answer in the retrieved notes' structured summaries (quick + detailed + key claims), and calls the LLM via `LLMClient.answer_question()`.
- Answers use only saved notes (no live web search per the MVP rule); the system prompt forbids outside knowledge and asks for cited note ids.
- `/ask <question>` runs in a background task and replies with the answer plus a `Sources:` list of `/more <id>` shortcuts.
- Degrades gracefully: missing embedding/LLM config, an empty index, no relevant matches, or an LLM error each return a clear message instead of failing.

## Verified

Automated checks currently pass:

```sh
python -m compileall src tests
PYTHONPATH=src python -m unittest discover -s tests
```

Current unit suite: 138 tests, all passing with `python-telegram-bot` installed. Bot-handler tests are skipped in host Python environments where `python-telegram-bot` is not installed; the Docker image installs it.

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
- `/ask` and `/idea` draw on note metadata/summaries (not full archived text), so answers and ideas are only as good as the saved summaries and the retrieved slice.
- GitHub support fetches README metadata/content only; it does not clone or inspect repo structure.
- LLM generation and embedding/indexing are synchronous in the Telegram request path, so slow providers can delay replies.
- LLM or embedding provider rate limits surface in SQLite as failed statuses; use `/reprocess <id>` or the rebuild CLI to retry.

## Next Recommended Work

Phases 1–6 and the full MVP scope are now implemented. Suggested follow-ups:

1. Add note-editing commands beyond deletion, such as rename, retag, and reviewed/useful status markers.
2. Add optional local embedding/LLM backend support if direct API costs or reliability become an issue.
3. Scheduled daily/weekly ideas.
4. Browser-rendered fetching for JavaScript-heavy pages.

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

Inspect generated ideas and ratings:

```sh
sqlite3 runtime/prism.sqlite3 "select idea_id,title,rating,llm_status from ideas order by created_at desc limit 10;"
```

Reprocess a note from Telegram:

```text
/reprocess <note_id>
```

Generate and rate ideas from Telegram:

```text
/idea robotics
/idea
/ideas
```

Ask a question grounded in your notes:

```text
/ask What have I saved about efficient VLMs for robotics?
```

Search related notes from Telegram:

```text
/related robotics
/related <note_id>
```

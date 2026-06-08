# Architecture

PRISM is a self-hosted research memory with four front ends over one shared service layer:

- Telegram bot (`prism-bot`) for capture and command workflows.
- Web UI (`prism-web`) for graph browsing, search, note actions, proposals, and profile editing.
- Terminal UI (`prism-tui`) for full-screen local operation.
- CLI (`prism-cli`) for scriptable commands.

All front ends share the same runtime data under `runtime/` or `/data` in Docker. SQLite and Markdown are the durable sources of truth; LanceDB is a rebuildable vector cache.

## Capture Pipeline

1. A URL or uploaded PDF reaches `NoteService` in `src/prism/notes.py`.
2. `src/prism/fetch.py` detects source type, fetches or extracts content, writes archives, and returns a `FetchResult`.
3. `src/prism/llm.py` optionally runs two OpenAI-compatible chat passes: a **ground-truth** pass (`generate_note`, source text only) for summaries, tags, scores, and related-note suggestions, then a **personalization** pass (`personalize_note`, ground truth + personal profile, no source) for profile-specific prose and relevance scores. The split lets personalization be re-run cheaply when the profile changes (`repersonalize` / `repersonalize_all`) without disturbing the objective summary or embedding.
4. `src/prism/db.py` persists note metadata and processing status in SQLite.
5. `render_note()` writes an Obsidian-compatible Markdown note into the vault.
6. `src/prism/index.py` optionally embeds the canonical note text and upserts it into LanceDB.

Each stage records status fields and degrades gracefully. Fetch, LLM, or embedding failures should create a partial note rather than losing the capture.

## Runtime Data

- `runtime/research-vault/notes/`: generated source notes.
- `runtime/research-vault/generated-ideas/`: generated idea notes.
- `runtime/research-vault/profile/personal.md`: user profile sent to LLM workflows.
- `runtime/prism.sqlite3`: note, idea, proposal, and usage metadata.
- `runtime/archives/<note_id>/`: raw/extracted source material and metadata.
- `runtime/lancedb/`: semantic index cache.

These paths are intentionally ignored by git.

## Web API

`src/prism/web/app.py` creates one FastAPI app. Routes live under `/api`; if a built frontend bundle exists, it is mounted as a static single-page app at `/`. On a network-exposed bind, the web UI uses an owner login backed by a signed session cookie. On first run, the UI can create the owner account and stores the hashed credential under `runtime/`; setting `PRISM_WEB_USERNAME` and `PRISM_WEB_PASSWORD` pins the credential and disables in-UI account creation.

The web process does not require Telegram configuration. It loads shared services lazily through `src/prism/web/deps.py`, which makes tests and local CLI workflows easier to isolate.

## Background Worker

`prism-worker` runs scheduled jobs configured by `runtime/feeds.yaml`:

- Feed ingestion saves RSS/digest links through the normal capture pipeline.
- Graph traversal refreshes automatic semantic links, normalizes near-duplicate tags, and creates merge proposals.
- Backup optionally commits the vault locally and snapshots SQLite.
- Re-embed optionally refreshes stale vector records.

Worker jobs can also be triggered manually from Telegram, the web UI, or `prism-cli`.

## Safety Boundaries

- Telegram command access is restricted by numeric user IDs.
- The web UI should remain localhost/VPN/LAN only; network-exposed binds require the owner-login flow or pinned `PRISM_WEB_USERNAME`/`PRISM_WEB_PASSWORD` credentials.
- URL fetching blocks private and local IP targets by default to reduce SSRF risk.
- Destructive actions use confirmations in Telegram/TUI, but web access is owner-level access.

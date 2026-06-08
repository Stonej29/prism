# Usage

How to drive PRISM day to day — commands, the web and terminal interfaces, the background worker, and maintenance. For setup see the [README](README.md); for design see [ARCHITECTURE.md](ARCHITECTURE.md).

## Commands

| Command | Description |
| --- | --- |
| *(send a URL)* | Save, archive, summarize, and index the link |
| *(upload a PDF)* | Save and process a PDF document directly |
| `/more <id>` | Structured detailed view of a note or idea |
| `/ask <question>` | Answer a question grounded only in your saved notes |
| `/find <query>` | Hybrid search (semantic + keyword; works even without embeddings) |
| `/related <query-or-id> [n]` | Semantic search for related notes |
| `/recent` | Browse recent notes (◀/▶ paged; hides archived) |
| `/inbox` | Browse unreviewed notes (the review queue) |
| `/tags [tag]` | Browse tag counts, or notes for a tag (◀/▶ paged) |
| `/idea [topic]` | Generate a project idea from your notes |
| `/ideas` | Browse generated ideas with their ratings (◀/▶ paged) |
| `/proposals` | Review graph-maintenance proposals (inline approve/reject) |
| `/ingest` | Pull configured feeds now (instead of waiting for the schedule) |
| `/traverse` | Run graph maintenance now (refresh links, normalize tags, propose merges) |
| `/status` | Note / LLM / embedding counts and index state |
| `/rename <id> <title>` | Rename a note (re-embeds; updates the vault frontmatter) |
| `/status_set <id> <status>` | Set a note's review status (`unreviewed` / `reviewed` / `archived`); archived notes drop out of the default lists |
| `/reprocess <id>` | Re-run LLM generation from archived text |
| `/retry_failed [n]` | Retry failed LLM or embedding work for up to `n` notes |
| `/delete <id>` | Delete a note or idea (inline yes/no confirmation) |
| `/wipe_all` | Wipe all notes, ideas, archives, and index cache (random code required) |
| `/reset_me <text>` | Replace your personal profile from the supplied text |
| `/update_me <text>` | Merge new facts into your personal profile |
| `/help` | List all commands |

## Web interface

PRISM ships a self-hosted **web UI** — a dark, three-pane "Atlas" workspace that runs alongside the bot and shares the same vault, database, and index:

- **Left** — a VSCode-style file explorer of the vault and archive (open PDFs, READMEs, and `personal.md` in an in-app viewer), plus source/tag filters and a name filter.
- **Center** — an interactive, force-directed **graph** of your notes and their links; click a node to open it, or use a note's **related** button to highlight its neighbors.
- **Right** — the full note (summary, key claims, scores, backlinks, tags, metadata) in collapsible sections. Both side panels fold and are drag-resizable.
- **Top bar** — `/ask` and `/find` (toggle the icon), a `+` to save a URL, and a 💡 lightbulb that generates an idea in the background.
- **Settings** (gear icon) — edit the personal profile, run feeds/maintenance, set **Connections** (LLM/embedding base URL, model, and API keys — stored privately, applied live), and manage your **Account** (change password, log out). Fields configured via environment variables show as locked.

It exposes the same actions as the bot: save URLs, ask, find, generate and rate ideas, reprocess, edit tags, rename (double-click the title), set review status, and delete.

Run it as a second container (shares `runtime/`; the bot is untouched):

```sh
docker compose build prism-web
docker compose up -d prism-web      # serves http://<host>:5890
```

Docker Compose publishes the web UI on all interfaces (`5890:5890`), so it is reachable from other devices on your network. The UI has full owner access (delete, reprocess, profile editing, feed ingestion), so on a network-exposed bind it requires a login. On first run it shows a **"create your account"** screen; pick a username and password and that credential is stored (hashed) under `runtime/`. A signed session cookie keeps you signed in afterwards. Because that first-run setup is open until an account exists, keep PRISM on a trusted LAN/VPN and create the account promptly — or pin the credential ahead of time by setting `PRISM_WEB_USERNAME`/`PRISM_WEB_PASSWORD` (which also disables in-UI account creation). Do not expose PRISM directly to the public internet. To run loopback-only with no login, set `PRISM_WEB_HOST=127.0.0.1` and bind the Compose port to `127.0.0.1:5890:5890`.

**Local development** — FastAPI with autoreload plus the Vite dev server proxying `/api`:

```sh
# Terminal 1 — API (shares runtime/ with the bot)
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb \
  VAULT_PATH=runtime/research-vault ARCHIVE_PATH=runtime/archives \
  PRISM_WEB_HOST=127.0.0.1 PRISM_WEB_RELOAD=1 python -m prism.web
# Terminal 2 — frontend
cd frontend && npm install && npm run dev
```

The web service ignores the Telegram env vars; optional knobs: `PRISM_WEB_HOST`, `PRISM_WEB_PORT`, `PRISM_WEB_RELOAD`, `PRISM_WEB_STATIC`, `PRISM_WEB_USERNAME`, and `PRISM_WEB_PASSWORD`.

## Terminal interface

PRISM also runs in the terminal — over the same vault, database, and index, with full feature parity with the bot. Two front-ends share one logic layer:

- **TUI** (`prism-tui`) — a full-screen [Textual](https://textual.textualize.io/) three-pane app: a mode-switchable sidebar (notes · ideas · tags · proposals), a Markdown detail pane, and a command bar. Use `1`–`4` to switch the list, `/` to type a command (`find …`, `ask …`, paste a URL to save), `r`/`d`/`a`/`x`/`g` to rate/delete/approve/reject/reprocess the selection, and `?` for the full command list. Network work runs off the UI thread, so it never blocks.
- **CLI** (`prism-cli`) — a scriptable, pipe-friendly front-end whose subcommands map 1:1 to the bot's commands (`save`, `find`, `ask`, `recent`, `idea`, `ingest`, `status`, `rename`, `set-status`, …) with plain-text output.

Both read the same env vars as the bot/worker and need no Telegram token:

```sh
# Full-screen TUI
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb \
  VAULT_PATH=runtime/research-vault ARCHIVE_PATH=runtime/archives \
  PRISM_FEEDS_PATH=runtime/feeds.yaml python -m prism.tui

# Scriptable CLI (same env vars)
PYTHONPATH=src ... python -m prism.cli recent
PYTHONPATH=src ... python -m prism.cli find "state space models"
PYTHONPATH=src ... python -m prism.cli status
```

## Background worker

An optional third container, `prism-worker`, runs scheduled jobs against the same `runtime/`:

- **Feed ingestion** (default daily 07:00) — pulls configured feeds and saves new items through the normal pipeline, tagged `input_source: ai_search`; dedup keeps re-polling cheap. Two feed types: `rss` saves each entry's own link (one note per entry), while `digest` handles roundup newsletters — it follows each post's **"Read more"** links to the underlying repos/papers/project pages and saves *those* as individual notes (one tech per note), not the digest post itself.
- **Graph maintenance** (default weekly, Monday 05:00) — applied automatically: refreshes each note's semantic related-links (recomputed each run, so they stay current instead of piling up) and normalizes near-duplicate tags corpus-wide (e.g. `foundation-model` / `foundation-models`). Near-duplicate *notes* are flagged as **merge proposals** for you to approve or reject via `/proposals` or the web UI. Approving a merge has the LLM **synthesize one consolidated note** from both (unioning their tags and links and re-pointing backlinks) before removing the duplicate — nothing is deleted without your approval, and no content is lost.
- **Backup** (opt-in `backup_enabled`, default daily 02:00) — commits the vault git repo (locally, no push) and writes a timestamped SQLite snapshot under `runtime/backups/`, keeping the most recent 14.
- **Re-embed** (opt-in `reembed_enabled`, default weekly Sunday 03:00) — re-embeds only notes whose index text changed since they were last embedded (cheaper than a full index rebuild), so edits and merges don't leave stale vectors.

Schedules use the `timezone` in `feeds.yaml` (default `Europe/Copenhagen`, DST-aware). Both jobs can also be triggered on demand without the worker container — from Telegram (`/ingest`, `/traverse`) or the web UI (buttons in the proposals panel), or via `docker compose run --rm prism-worker python -m prism.worker ingest`.

Configure feeds and schedules in `runtime/feeds.yaml` (copy `feeds.example.yaml`):

```sh
cp feeds.example.yaml runtime/feeds.yaml   # edit feeds + cron schedules
docker compose build prism-worker
docker compose up -d prism-worker
# Run a job once, without waiting for the schedule:
docker compose run --rm prism-worker python -m prism.worker ingest    # also: backup | reembed
```

## Maintenance

Rebuild the semantic index from SQLite at any time:

```sh
docker compose run --rm prism python -m prism.index rebuild
```

Inspect processing status:

```sh
sqlite3 runtime/prism.sqlite3 "select note_id,title,llm_status,embedding_status from notes order by date_saved desc limit 10;"
sqlite3 runtime/prism.sqlite3 "select idea_id,title,rating,llm_status from ideas order by created_at desc limit 10;"
```

Run the test suite:

```sh
PYTHONPATH=src python -m unittest discover -s tests
```

For where this data lives on disk, see [ARCHITECTURE.md](ARCHITECTURE.md#runtime-data).

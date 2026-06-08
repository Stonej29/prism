# PRISM

[![CI](https://github.com/Stonej29/prism/actions/workflows/ci.yml/badge.svg)](https://github.com/Stonej29/prism/actions/workflows/ci.yml)

**Personal Research Interlinked System** — a self-hosted research memory (a Telegram bot plus a web UI) that turns links into a structured, searchable knowledge base.

Send a URL and PRISM fetches it, archives the source, generates a rich LLM summary, embeds it into a semantic index, and saves an Obsidian-compatible Markdown note with tags, evaluation scores, and backlinks to related notes. Over time it becomes a personal research memory you can browse, search, and ask questions against — and generate new project ideas from. Drive it from Telegram, from a graph-based [web interface](#web-interface), or from the [terminal](#terminal-interface) (full-screen TUI or scriptable CLI).

Supported source types: arXiv papers, GitHub repos, Hugging Face models/datasets/papers, YouTube videos (title + transcript), PDFs (by URL or uploaded directly to the bot), and general websites.

Every note also records an `input_source` — how it entered PRISM (`telegram`, `web_ui`, `ai_search`, `scheduled`, …) — kept distinct from `source_kind` (what the content is), so pipelines and feeds can be filtered and tracked separately.

## What it does

- **Save** — send any URL (or upload a PDF) to the bot; it archives and processes it automatically
- **Summarize** — LLM generates title, summary, key claims, limitations, tags, and scores
- **Connect** — semantic search links each note to related ones via Obsidian backlinks
- **Search** — `/find`, `/related`, and `/ask` let you query your knowledge base
- **Ideate** — `/idea` synthesizes project ideas from your notes; rate them 1–5 to steer future ones
- **Automate** — an optional background worker pulls configured RSS/Atom feeds on a schedule and performs graph maintenance, proposing near-duplicate merges for you to approve via `/proposals` or the web UI

Every step degrades gracefully: a fetch, LLM, or embedding failure produces a partial note rather than losing the capture.

## Quick start

Needs Docker. From the repo root:

```sh
git clone <repo> && cd prism
./setup.sh        # scaffolds .env, inits the vault, builds, and starts the stack
```

Then open the **web UI at `http://localhost:8000`**, create your owner account, and add your LLM / embedding / Telegram keys under **Settings → Connections**. Nothing has to be put in `.env` by hand.

- **Telegram bot** — it stays idle until its token + allowed IDs are set (in the UI or `.env`), then connects within ~20s. Get the token from [@BotFather](https://t.me/BotFather), your user ID from [@userinfobot](https://t.me/userinfobot).
- **Prefer the terminal / no web UI?** Set `LLM_*`, `EMBEDDING_*`, and `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USER_IDS` in `.env` before running. Env values take precedence and lock the matching UI fields.

> **Fedora/RHEL:** install Docker first — `sudo dnf install docker docker-compose-plugin && sudo systemctl enable --now docker`

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

PRISM also ships a self-hosted **web UI** — a dark, three-pane "Atlas" workspace that runs alongside the bot and shares the same vault, database, and index:

- **Left** — a VSCode-style file explorer of the vault and archive (open PDFs, READMEs, and `personal.md` in an in-app viewer), plus source/tag filters and a name filter.
- **Center** — an interactive, force-directed **graph** of your notes and their links; click a node to open it, or use a note's **related** button to highlight its neighbors.
- **Right** — the full note (summary, key claims, scores, backlinks, tags, metadata) in collapsible sections. Both side panels fold and are drag-resizable.
- **Top bar** — `/ask` and `/find` (toggle the icon), a `+` to save a URL, and a 💡 lightbulb that generates an idea in the background.
- **Settings** (gear icon) — edit the personal profile, run feeds/maintenance, set **Connections** (LLM/embedding base URL, model, and API keys — stored privately, applied live), and manage your **Account** (change password, log out). Fields configured via environment variables show as locked.

It exposes the same actions as the bot: save URLs, ask, find, generate and rate ideas, reprocess, edit tags, rename (double-click the title), set review status, and delete.

Run it as a second container (shares `runtime/`; the bot is untouched):

```sh
docker compose build prism-web
docker compose up -d prism-web      # serves http://<host>:8000
```

Docker Compose publishes the web UI on all interfaces (`8000:8000`), so it is reachable from other devices on your network. The UI has full owner access (delete, reprocess, profile editing, feed ingestion), so on a network-exposed bind it requires a login. On first run it shows a **"create your account"** screen; pick a username and password and that credential is stored (hashed) under `runtime/`. A signed session cookie keeps you signed in afterwards. Because that first-run setup is open until an account exists, keep PRISM on a trusted LAN/VPN and create the account promptly — or pin the credential ahead of time by setting `PRISM_WEB_USERNAME`/`PRISM_WEB_PASSWORD` (which also disables in-UI account creation). Do not expose PRISM directly to the public internet. To run loopback-only with no login, set `PRISM_WEB_HOST=127.0.0.1` and bind the Compose port to `127.0.0.1:8000:8000`.

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

## Security and privacy

PRISM is designed as a self-hosted personal system. Treat the runtime vault, SQLite database, archives, profile, and `.env` as private data.

- The Telegram bot requires `TELEGRAM_ALLOWED_USER_IDS` and rejects other users.
- The web UI should stay on localhost, a trusted LAN, or a VPN. If you expose it beyond localhost, set `PRISM_WEB_USERNAME` and `PRISM_WEB_PASSWORD` or put it behind an authenticated reverse proxy.
- The fetcher blocks localhost, private, link-local, multicast, reserved, and unspecified IP targets by default to reduce SSRF risk. Set `PRISM_FETCH_ALLOW_PRIVATE=1` only if you deliberately need to capture private-network URLs.
- LLM and embedding providers receive the text and profile context needed for the requested operation. The optional blocked-page reader fallback sends blocked URLs to `r.jina.ai`. Set `PRISM_FETCH_USE_JINA_READER=0` if that does not fit your privacy model.
- `docker compose config` expands `.env` values; do not paste that output publicly without redacting secrets.

See `SECURITY.md` for more release and deployment guidance.

## Stack

Python · `python-telegram-bot` · FastAPI · React + Vite (TypeScript) · Textual (TUI) · Obsidian-compatible Markdown vault · SQLite · LanceDB · OpenAI-compatible LLM and embedding APIs. Requires Python ≥ 3.12 (and Node ≥ 18 to build the web UI); runs via Docker Compose.

## Runtime data

All data lives in `runtime/` (Docker volume mount, excluded from this repo):

| Path | Contents |
| --- | --- |
| `runtime/research-vault/notes/` | Generated source notes (Markdown) |
| `runtime/research-vault/generated-ideas/` | Generated idea notes (Markdown) |
| `runtime/research-vault/profile/personal.md` | Personal profile fed to the LLM |
| `runtime/prism.sqlite3` | Note and idea metadata |
| `runtime/archives/<note_id>/` | Raw HTML/PDF/README, extracted text, metadata JSON |
| `runtime/lancedb/` | Vector index (rebuildable cache; SQLite + Markdown are authoritative) |

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

## Architecture

See `ARCHITECTURE.md` for the public architecture, data flow, and design decisions.

## License

Released under the [MIT License](LICENSE).

## Planned

- [x] Terminal interface (TUI + CLI)
- [x] Web interface
- [x] Direct PDF uploads, YouTube, and Hugging Face sources
- [x] Scheduled feed ingestion + AI graph maintenance (background worker)
- [ ] Browser extension / iOS Shortcut for frictionless link sharing
- [ ] Scheduled idea generation (daily/weekly)
- [x] Note editing commands (rename, retag, review status)
- [ ] Local LLM and embedding support

# PRISM

**Personal Research Interlinked System** — a self-hosted research memory (a Telegram bot plus a web UI) that turns links into a structured, searchable knowledge base.

Send a URL and PRISM fetches it, archives the source, generates a rich LLM summary, embeds it into a semantic index, and saves an Obsidian-compatible Markdown note with tags, evaluation scores, and backlinks to related notes. Over time it becomes a personal research memory you can browse, search, and ask questions against — and generate new project ideas from. Drive it from Telegram, or from a graph-based [web interface](#web-interface).

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

## Setup

**1. Clone and configure**

```sh
git clone <repo>
cd prism
cp .env.example .env
```

Edit `.env` — at minimum set:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_USER_IDS=your_telegram_user_id
```

Get your bot token from [@BotFather](https://t.me/BotFather). Get your user ID from [@userinfobot](https://t.me/userinfobot).

**2. Add LLM and embedding services (optional but recommended)**

Without these, links are still fetched and archived but notes won't be summarized and semantic search won't work.

```env
LLM_BASE_URL=https://openrouter.ai/api/v1   # default; change for other providers
LLM_API_KEY=your_key
LLM_MODEL=google/gemini-2.5-flash           # or any OpenAI-compatible model

EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=your_key
EMBEDDING_MODEL=text-embedding-3-small
```

**3. Initialize the vault**

```sh
mkdir -p runtime/research-vault
git -C runtime/research-vault init
printf ".obsidian/workspace*.json\n.trash/\n" > runtime/research-vault/.gitignore
```

**4. Build and run**

```sh
docker compose build
sudo docker compose up -d --force-recreate
sudo docker compose logs -f prism
```

Open Telegram, find your bot, and send a link.

> **Fedora/RHEL note:** install Docker first:
> ```sh
> sudo dnf install docker docker-compose-plugin
> sudo systemctl enable --now docker
> ```

## Commands

| Command | Description |
| --- | --- |
| *(send a URL)* | Save, archive, summarize, and index the link |
| *(upload a PDF)* | Save and process a PDF document directly |
| `/more <id>` | Structured detailed view of a note or idea |
| `/ask <question>` | Answer a question grounded only in your saved notes |
| `/find <query>` | Semantic search by free-text query |
| `/related <query-or-id> [n]` | Semantic search for related notes |
| `/recent` | Browse recent notes (◀/▶ paged) |
| `/tags [tag]` | Browse tag counts, or notes for a tag (◀/▶ paged) |
| `/idea [topic]` | Generate a project idea from your notes |
| `/ideas` | Browse generated ideas with their ratings (◀/▶ paged) |
| `/proposals` | Review graph-maintenance proposals (inline approve/reject) |
| `/ingest` | Pull configured feeds now (instead of waiting for the schedule) |
| `/traverse` | Run graph maintenance now (refresh links, normalize tags, propose merges) |
| `/status` | Note / LLM / embedding counts and index state |
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

It exposes the same actions as the bot: save URLs, ask, find, generate and rate ideas, reprocess, edit tags, and delete.

Run it as a second container (shares `runtime/`; the bot is untouched):

```sh
docker compose build prism-web
docker compose up -d prism-web      # serves http://localhost:8000
```

It binds `0.0.0.0:8000`, so it's reachable from other devices on your network at `http://<host-ip>:8000`. There is **no authentication** — keep it on a trusted LAN/VPN (e.g. Tailscale), not the public internet.

**Local development** — FastAPI with autoreload plus the Vite dev server proxying `/api`:

```sh
# Terminal 1 — API (shares runtime/ with the bot)
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb \
  VAULT_PATH=runtime/research-vault ARCHIVE_PATH=runtime/archives \
  PRISM_WEB_RELOAD=1 python -m prism.web
# Terminal 2 — frontend
cd frontend && npm install && npm run dev
```

The web service ignores the Telegram env vars; optional knobs: `PRISM_WEB_HOST`, `PRISM_WEB_PORT`, `PRISM_WEB_RELOAD`, `PRISM_WEB_STATIC`.

## Background worker

An optional third container, `prism-worker`, runs scheduled jobs against the same `runtime/`:

- **Feed ingestion** (default daily 07:00) — pulls configured feeds and saves new items through the normal pipeline, tagged `input_source: ai_search`; dedup keeps re-polling cheap. Two feed types: `rss` saves each entry's own link (one note per entry), while `digest` handles roundup newsletters — it follows each post's **"Read more"** links to the underlying repos/papers/project pages and saves *those* as individual notes (one tech per note), not the digest post itself.
- **Graph maintenance** (default weekly, Monday 05:00) — applied automatically: refreshes each note's semantic related-links (recomputed each run, so they stay current instead of piling up) and normalizes near-duplicate tags corpus-wide (e.g. `foundation-model` / `foundation-models`). Near-duplicate *notes* are flagged as **merge proposals** for you to approve or reject via `/proposals` or the web UI. Approving a merge has the LLM **synthesize one consolidated note** from both (unioning their tags and links and re-pointing backlinks) before removing the duplicate — nothing is deleted without your approval, and no content is lost.

Schedules use the `timezone` in `feeds.yaml` (default `Europe/Copenhagen`, DST-aware). Both jobs can also be triggered on demand without the worker container — from Telegram (`/ingest`, `/traverse`) or the web UI (buttons in the proposals panel), or via `docker compose run --rm prism-worker python -m prism.worker ingest`.

Configure feeds and schedules in `runtime/feeds.yaml` (copy `feeds.example.yaml`):

```sh
cp feeds.example.yaml runtime/feeds.yaml   # edit feeds + cron schedules
docker compose build prism-worker
docker compose up -d prism-worker
# Run a job once, without waiting for the schedule:
docker compose run --rm prism-worker python -m prism.worker ingest
```

## Stack

Python · `python-telegram-bot` · FastAPI · React + Vite (TypeScript) · Obsidian-compatible Markdown vault · SQLite · LanceDB · OpenAI-compatible LLM and embedding APIs. Requires Python ≥ 3.12 (and Node ≥ 18 to build the web UI); runs via Docker Compose.

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

See `CLAUDE.md` for the full architecture, data flow, and design decisions.

## Planned

- [ ] Terminal interface
- [x] Web interface
- [x] Direct PDF uploads, YouTube, and Hugging Face sources
- [x] Scheduled feed ingestion + AI graph maintenance (background worker)
- [ ] Browser extension / iOS Shortcut for frictionless link sharing
- [ ] Scheduled idea generation (daily/weekly)
- [ ] Note editing commands (rename, retag, review status)
- [ ] Local LLM and embedding support

# PRISM

**Personal Research Interlinked System** — a self-hosted Telegram bot that turns links into a structured, searchable knowledge base.

Send a URL and PRISM fetches it, archives the source, generates a rich LLM summary, embeds it into a semantic index, and saves an Obsidian-compatible Markdown note with tags, evaluation scores, and backlinks to related notes. Over time it becomes a personal research memory you can browse, search, and ask questions against — and generate new project ideas from.

Supported source types: arXiv papers, GitHub repos, PDFs, and general websites.

## What it does

- **Save** — send any URL to the bot; it archives and processes it automatically
- **Summarize** — LLM generates title, summary, key claims, limitations, tags, and scores
- **Connect** — semantic search links each note to related ones via Obsidian backlinks
- **Search** — `/find`, `/related`, and `/ask` let you query your knowledge base
- **Ideate** — `/idea` synthesizes project ideas from your notes; rate them 1–5 to steer future ones

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
| `/more <id>` | Structured detailed view of a note or idea |
| `/ask <question>` | Answer a question grounded only in your saved notes |
| `/find <query>` | Semantic search by free-text query |
| `/related <query-or-id> [n]` | Semantic search for related notes |
| `/recent` | Browse recent notes (◀/▶ paged) |
| `/tags [tag]` | Browse tag counts, or notes for a tag (◀/▶ paged) |
| `/idea [topic]` | Generate a project idea from your notes |
| `/ideas` | Browse generated ideas with their ratings (◀/▶ paged) |
| `/status` | Note / LLM / embedding counts and index state |
| `/reprocess <id>` | Re-run LLM generation from archived text |
| `/retry_failed [n]` | Retry failed LLM or embedding work for up to `n` notes |
| `/delete <id>` | Delete a note or idea (inline yes/no confirmation) |
| `/wipe_all` | Wipe all notes, ideas, archives, and index cache (random code required) |
| `/reset_me <text>` | Replace your personal profile from the supplied text |
| `/update_me <text>` | Merge new facts into your personal profile |
| `/help` | List all commands |

## Stack

Python · `python-telegram-bot` · Obsidian-compatible Markdown vault · SQLite · LanceDB · OpenAI-compatible LLM and embedding APIs. Requires Python ≥ 3.12; runs via Docker Compose.

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

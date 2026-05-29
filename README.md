# PRISM

**Personal Research Interlinked System** — a self-hosted research memory and idea engine.

Send a URL to a Telegram bot and PRISM resolves, fetches, archives, and extracts the
source; generates a structured, Obsidian-compatible Markdown note with an LLM; embeds
it into a LanceDB semantic index with backlinks to related notes; and stores all
metadata in SQLite. You can then browse, search, and synthesize new project ideas from
your saved knowledge — and rate those ideas 1–5 to steer future ones.

Every step degrades gracefully: a fetch, LLM, or embedding failure produces a partial
note rather than losing the capture.

## Pipeline

```
Telegram message → handle_message → NoteService.save_url
  → fetch_source (fetch.py)         → runtime/archives/<id>/   (extracted.txt, metadata.json, raw source)
  → _apply_llm (llm.py)             → structured JSON fields (summary, tags, scores, related)
  → render_note (notes.py)          → runtime/research-vault/notes/<date>-<slug>.md
  → database.insert_note (db.py)    → runtime/prism.sqlite3
  → _index_after_persist (index.py) → runtime/lancedb/
```

Source kinds detected automatically: arXiv papers, GitHub repos (README + metadata),
PDFs, and general websites. See `CLAUDE.md` for the full architecture and design notes.

## Telegram commands

| Command | Description |
| --- | --- |
| *(send a URL)* | Save, archive, summarize, and index the link |
| `/start` | Intro message |
| `/help` | List all commands |
| `/more <id>` | Show the structured detailed view of a note |
| `/related <query-or-note_id> [n]` | Semantic search for related notes |
| `/find <query>` | Semantic search by free-text query |
| `/ask <question>` | Answer a question grounded only in your saved notes, with cited sources |
| `/recent` | Browse recent notes (◀/▶ paged) |
| `/tags [tag]` | Browse tag counts, or notes for a tag (◀/▶ paged) |
| `/status` | Note / LLM / embedding counts and index state |
| `/reprocess <id>` | Re-run LLM generation from the archived text |
| `/retry_failed [n]` | Retry failed LLM generation or embedding/indexing for up to `n` notes |
| `/delete <id>` | Delete a note or generated idea after an inline yes/no confirmation |
| `/wipe_all` | Generate a random confirmation code for wiping all saved notes, ideas, archives, and index cache |
| `/idea [topic]` | Generate a project idea from your notes (semantic search on a topic, else recent notes) |
| `/ideas` | Browse generated ideas with their ratings (◀/▶ paged) |
| *(★1–★5 buttons)* | Rate the idea under each `/idea` reply (1–5) |

## Stack

Python · `python-telegram-bot` · Markdown/Obsidian vault · SQLite (metadata) ·
LanceDB (vectors) · local filesystem (archive) · OpenAI-compatible LLM and embedding
APIs. Requires Python ≥ 3.12; runs via Docker Compose.

## Configuration

Copy `.env.example` to `.env` and set:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS` — comma-separated numeric Telegram user IDs
- `PRISM_UID` / `PRISM_GID` if your host user is not `1000:1000`

Optional services (each degrades gracefully if unset):

- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` — note and idea generation (default base URL: OpenRouter)
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` — semantic indexing, `/related`, `/find`, and topic-based `/idea` (default base URL: OpenAI)

Without an LLM key, links are still fetched and archived (notes are degraded, and
`/idea` is unavailable). Without an embedding key, semantic search and indexing are
skipped but everything else works.

`VAULT_PATH`, `SQLITE_PATH`, `ARCHIVE_PATH`, and `LANCEDB_PATH` default to paths under
`/data` inside the container.

## Fedora Docker setup

```sh
sudo dnf install docker docker-compose-plugin
sudo systemctl enable --now docker
docker compose version
```

Either add your user to the Docker group and log out/in, or prefix commands with `sudo`:

```sh
sudo usermod -aG docker "$USER"
```

## Initialize the private vault

The Obsidian vault is its own local git repo with no remote, kept out of this repo:

```sh
mkdir -p runtime/research-vault
git -C runtime/research-vault init
printf ".obsidian/workspace*.json\n.trash/\n" > runtime/research-vault/.gitignore
```

## Build and run

```sh
docker compose build
sudo docker compose up -d --force-recreate
sudo docker compose logs -f prism
```

## Maintenance

Rebuild the semantic index from SQLite (the source of truth) at any time:

```sh
docker compose run --rm prism python -m prism.index rebuild
# or on the host:
PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb python -m prism.index rebuild
```

Inspect processing status:

```sh
sqlite3 runtime/prism.sqlite3 "select note_id,title,llm_status,embedding_status from notes order by date_saved desc limit 10;"
sqlite3 runtime/prism.sqlite3 "select idea_id,title,rating,llm_status from ideas order by created_at desc limit 10;"
```

Run the test suite (installs `python-telegram-bot` for the bot-handler tests):

```sh
PYTHONPATH=src python -m unittest discover -s tests
```

## Runtime data layout

Runtime data is intentionally kept out of this repository (`runtime/` is a Docker
volume mount):

- `runtime/research-vault/notes/` — generated source notes (Markdown)
- `runtime/research-vault/generated-ideas/` — generated idea notes (Markdown)
- `runtime/research-vault/profile/personal.md` — personal profile fed to the LLM
- `runtime/prism.sqlite3` — note and idea metadata
- `runtime/archives/<note_id>/` — raw HTML/PDF/README, extracted text, metadata JSON
- `runtime/lancedb/` — vector index (a rebuildable cache; SQLite + Markdown are authoritative)

## Implementation status

The full `overview.md` **MVP scope** is implemented, including `/ask`
retrieval-augmented Q&A grounded in saved notes. Build plan Phases 1–6 are complete.
See `status.md` for the detailed breakdown.

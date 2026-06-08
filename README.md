# PRISM

[![CI](https://github.com/Stonej29/prism/actions/workflows/ci.yml/badge.svg)](https://github.com/Stonej29/prism/actions/workflows/ci.yml)

**Personal Research Interlinked System** — a self-hosted research memory (a Telegram bot plus a web UI) that turns links into a structured, searchable knowledge base.

Send a URL and PRISM fetches it, archives the source, generates a rich LLM summary, embeds it into a semantic index, and saves an Obsidian-compatible Markdown note with tags, evaluation scores, and backlinks to related notes. Over time it becomes a personal research memory you can browse, search, and ask questions against — and generate new project ideas from. Drive it from Telegram, from a graph-based [web interface](USAGE.md#web-interface), or from the [terminal](USAGE.md#terminal-interface) (full-screen TUI or scriptable CLI).

Supported source types: arXiv papers, GitHub repos, Hugging Face models/datasets/papers, YouTube videos (title + transcript), PDFs (by URL or uploaded directly to the bot), and general websites.

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

Then open the **web UI at `http://localhost:5890`**, create your owner account, and add your LLM / embedding / Telegram keys under **Settings → Connections**. Nothing has to be put in `.env` by hand.

- **Telegram bot** — it stays idle until its token + allowed IDs are set (in the UI or `.env`), then connects within ~20s. Get the token from [@BotFather](https://t.me/BotFather), your user ID from [@userinfobot](https://t.me/userinfobot).
- **Prefer the terminal / no web UI?** Set `LLM_*`, `EMBEDDING_*`, and `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USER_IDS` in `.env` before running. Env values take precedence and lock the matching UI fields.

> **Fedora/RHEL:** install Docker first — `sudo dnf install docker docker-compose-plugin && sudo systemctl enable --now docker`

## Documentation

- [Usage](USAGE.md) — commands, web UI, terminal UI/CLI, background worker, and maintenance.
- [Architecture](ARCHITECTURE.md) — runtime data, capture pipeline, and design decisions.
- [Security](SECURITY.md) — deployment and security guidance.

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

## License

Released under the [MIT License](LICENSE).

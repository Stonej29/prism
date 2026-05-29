# prism

Personal Research Interlinked System (PRISM) is a self-hosted personal research memory and idea engine.

## Phase 2

Phase 2 runs a Docker Compose based Telegram bot. Send it a message containing a URL and it resolves, fetches, archives, and extracts source content before creating an Obsidian-compatible Markdown note in a private mounted vault and recording metadata in SQLite. If fetching fails, PRISM still creates a fallback note with the fetch error recorded.

Runtime data is intentionally kept out of the app repository:

- `runtime/research-vault` is the private Obsidian vault and should be its own local git repo with no remote.
- `runtime/prism.sqlite3` stores app metadata.
- `runtime/archives` stores raw fetched HTML, PDFs, README files, extracted text, and metadata JSON.
- `runtime/lancedb` and `runtime/logs` are reserved for later phases.

## Fedora Docker Setup

Install Docker and Compose:

```sh
sudo dnf install docker docker-compose-plugin
sudo systemctl enable --now docker
```

Either add your user to the Docker group and log out/in:

```sh
sudo usermod -aG docker "$USER"
```

Or run Compose commands with `sudo docker compose`.

Verify Docker:

```sh
docker compose version
```

## Local Setup

Create local config:

```sh
cp .env.example .env
```

Set:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS`, as comma-separated numeric Telegram user IDs
- `PRISM_UID` and `PRISM_GID` if your host user is not `1000:1000`

`VAULT_PATH`, `SQLITE_PATH`, and `ARCHIVE_PATH` default to paths under `/data` in Docker. LLM variables are present for future phases but are not used in Phase 2.

Initialize the private vault:

```sh
mkdir -p runtime/research-vault
git -C runtime/research-vault init
printf ".obsidian/workspace*.json\n.trash/\n" > runtime/research-vault/.gitignore
```

Build and run:

```sh
docker compose build
docker compose up
```

## Phase 2 Checks

- Send a URL from an allowed Telegram account.
- Confirm a note appears under `runtime/research-vault/notes/`.
- Confirm archived source files appear under `runtime/archives/<note_id>/`.
- Confirm SQLite has a matching row in `runtime/prism.sqlite3` with fetch metadata.
- Send the same exact URL again and confirm the bot returns an existing note response.
- Send a different URL with the same extracted content and confirm the existing note is reused.
- Send a message from an unauthorized Telegram account and confirm it is rejected.
- Run `git status --short` in this repo and confirm runtime data and secrets are ignored.
- Run `git -C runtime/research-vault status` to inspect the vault's separate git history.

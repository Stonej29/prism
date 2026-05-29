# prism

Personal Research Interlinked System (PRISM) is a self-hosted personal research memory and idea engine.

## Phase 1

Phase 1 runs a Docker Compose based Telegram bot. Send it a message containing a URL and it creates an Obsidian-compatible placeholder Markdown note in a private mounted vault, then records metadata in SQLite.

Runtime data is intentionally kept out of the app repository:

- `runtime/research-vault` is the private Obsidian vault and should be its own local git repo with no remote.
- `runtime/prism.sqlite3` stores app metadata.
- `runtime/lancedb`, `runtime/archives`, and `runtime/logs` are reserved for later phases.

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

LLM variables are present for future phases but are not used in Phase 1.

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

## Phase 1 Checks

- Send a URL from an allowed Telegram account.
- Confirm a note appears under `runtime/research-vault/notes/`.
- Confirm SQLite has a matching row in `runtime/prism.sqlite3`.
- Send the same exact URL again and confirm the bot returns an existing note response.
- Send a message from an unauthorized Telegram account and confirm it is rejected.
- Run `git status --short` in this repo and confirm runtime data and secrets are ignored.
- Run `git -C runtime/research-vault status` to inspect the vault's separate git history.

#!/usr/bin/env bash
# One-shot setup for PRISM. Idempotent — safe to re-run.
#
# Scaffolds .env, initializes the Obsidian vault repo, builds the images, and
# starts the stack. You then finish configuration in the web UI; nothing needs
# to be edited by hand.
set -euo pipefail
cd "$(dirname "$0")"

# Use sudo for docker only if the daemon isn't reachable without it.
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
  else
    echo "error: Docker isn't available. Install Docker and try again." >&2
    exit 1
  fi
fi

# 1. Scaffold .env (you can leave every value blank and configure in the web UI).
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi

# 2. Initialize the Obsidian vault as its own git repo.
if [ ! -d runtime/research-vault/.git ]; then
  mkdir -p runtime/research-vault
  git -C runtime/research-vault init -q
  printf ".obsidian/workspace*.json\n.trash/\n" > runtime/research-vault/.gitignore
  echo "Initialized runtime/research-vault."
fi

# 3. Build and start the stack.
$DOCKER compose build
$DOCKER compose up -d

cat <<'EOF'

PRISM is up.
  Web UI: http://localhost:8000
    -> create your owner account, then add your LLM / embedding / Telegram
       keys under Settings -> Connections.
  The Telegram bot stays idle until you add its token, then connects on its own.
EOF

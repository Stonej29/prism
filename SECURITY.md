# Security Policy

## Supported Versions

PRISM is a personal project. Until a stable release is tagged, security fixes are made on the default development branch and documented in pull requests or release notes.

## Reporting a Vulnerability

If this repository is public and you find a vulnerability, please open a private security advisory on GitHub if available. If advisories are not enabled, contact the maintainer privately rather than filing a public issue with exploit details.

Please include:

- Affected version or commit.
- A short description of the impact.
- Reproduction steps or a proof of concept.
- Whether secrets, personal data, runtime vault content, or third-party API accounts may be affected.

## Deployment Guidance

PRISM stores private research data and talks to external model providers. Do not run it as an unauthenticated public service.

- Keep `.env`, `runtime/`, the Obsidian vault, SQLite databases, archives, LanceDB files, logs, and backups private.
- Rotate `TELEGRAM_BOT_TOKEN`, LLM keys, and embedding keys if they appear in logs, shell history, screenshots, or shared Compose output.
- The Telegram bot is restricted by `TELEGRAM_ALLOWED_USER_IDS`; keep that list narrow.
- Docker Compose publishes the web UI on `127.0.0.1:8000` by default. For LAN/VPN use, set `PRISM_WEB_USERNAME` and `PRISM_WEB_PASSWORD`, or put the service behind an authenticated reverse proxy.
- The web UI supports destructive actions such as delete, reprocess, feed ingestion, graph maintenance, and profile editing. Treat web access as full owner access.
- Server-side fetching blocks private/local IPs by default. Set `PRISM_FETCH_ALLOW_PRIVATE=1` only when private-network capture is intentional.
- LLM and embedding providers receive note/profile context for enabled features. Review provider retention policies before using sensitive data.
- The blocked-page fallback uses `https://r.jina.ai/` as a reader proxy for some hard-blocked websites. Set `PRISM_FETCH_USE_JINA_READER=0` if those URLs are sensitive.

## Pre-Publication Secret Checklist

Before making a repository public:

- Run a secret scanner against the full git history.
- Verify `git status --ignored --short` only shows intentionally ignored local data.
- Confirm `.env` and `runtime/` were never committed.
- Rotate any credential that appeared in terminal output, CI logs, shell history, screenshots, or generated diagnostics.

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
- Docker Compose publishes the web UI on all interfaces (`5890:5890`), reachable from your LAN. On a network-exposed bind it requires a login: on first run the UI prompts you to create an owner account, stored as a PBKDF2 hash under `runtime/` (path overridable via `PRISM_WEB_AUTH_FILE`). That first-run setup screen is open until an account exists, so create it promptly on a trusted network — or pin the credential up front with `PRISM_WEB_USERNAME`/`PRISM_WEB_PASSWORD` (which disables in-UI creation), or front the service with an authenticated reverse proxy. Login state is a signed session cookie; over HTTPS also set `PRISM_WEB_COOKIE_SECURE=1`. To run loopback-only without a login, set `PRISM_WEB_HOST=127.0.0.1` and bind the port to `127.0.0.1:5890:5890`. Keep it on a trusted LAN/VPN; never expose it directly to the public internet.
- The web UI supports destructive actions such as delete, reprocess, feed ingestion, graph maintenance, profile editing, and **setting LLM/embedding/Telegram credentials**. Treat web access as full owner access.
- Credentials entered in the UI are written to a config store (`runtime/settings.json`, `0600`; path overridable via `PRISM_CONFIG_FILE`). API keys must be replayed to providers, so they are stored reversibly — protected by file permissions, the web login, and never returned to the browser. Prefer setting secrets via environment variables (which override and lock the UI fields) if you want them kept out of the runtime store. Treat `runtime/settings.json` as secret material in backups.
- Server-side fetching blocks private/local IPs by default. Set `PRISM_FETCH_ALLOW_PRIVATE=1` only when private-network capture is intentional.
- LLM and embedding providers receive note/profile context for enabled features. Review provider retention policies before using sensitive data.
- The blocked-page fallback uses `https://r.jina.ai/` as a reader proxy for some hard-blocked websites. Set `PRISM_FETCH_USE_JINA_READER=0` if those URLs are sensitive.

## Pre-Publication Secret Checklist

Before making a repository public:

- Run a secret scanner against the full git history.
- Verify `git status --ignored --short` only shows intentionally ignored local data.
- Confirm `.env` and `runtime/` were never committed.
- Rotate any credential that appeared in terminal output, CI logs, shell history, screenshots, or generated diagnostics.

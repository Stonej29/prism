# Repository Guidelines

## Project Structure & Module Organization

PRISM is a Python 3.12 package using a `src/` layout. Core code lives in `src/prism/`: `bot.py` wires Telegram handlers, `notes.py` orchestrates capture, `fetch.py` extracts source content, `llm.py` and `embedding.py` call external model APIs, `index.py` manages LanceDB, `db.py` owns SQLite persistence, and `ideas.py` handles generated ideas. Tests live in `tests/` and are organized by implementation phase plus focused command coverage. Runtime data is intentionally outside source control under `runtime/`, including the Obsidian vault, SQLite database, archives, and LanceDB cache.

## Build, Test, and Development Commands

- `PYTHONPATH=src python -m unittest discover -s tests` runs the full test suite.
- `PYTHONPATH=src python -m unittest tests.test_phase4` runs one test module.
- `python -m compileall src tests` checks Python syntax across source and tests.
- `docker compose build` builds the bot image.
- `sudo docker compose up -d --force-recreate` starts the local bot stack.
- `sudo docker compose logs -f prism` follows bot logs.
- `PYTHONPATH=src SQLITE_PATH=runtime/prism.sqlite3 LANCEDB_PATH=runtime/lancedb python -m prism.index rebuild` rebuilds the semantic index from SQLite.

## Coding Style & Naming Conventions

Follow standard Python style with 4-space indentation, type hints where useful, and small functions that preserve the current module boundaries. Use `snake_case` for functions, variables, database helpers, and test methods; use `PascalCase` for dataclasses and service classes such as `NoteService` and `IdeaService`. Keep failures graceful: fetch, LLM, and embedding errors should record status fields rather than losing a capture.

## Testing Guidelines

Use `unittest`; no pytest-specific features are required. Add tests under `tests/` with names like `test_<feature>.py` or extend the relevant phase test. Prefer deterministic tests with temporary paths and mocked network/model calls. Run the full suite before changing persistence, bot handlers, indexing, or note rendering.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries, often phase-oriented, such as `Implement Phase 5: background processing and retrieval commands`. Keep commits focused and mention user-visible commands or data migrations when relevant. Pull requests should include a concise description, test results, linked issues if any, and screenshots or log snippets only when bot output or operational behavior changes.

## Security & Configuration Tips

Do not commit `.env`, API keys, Telegram tokens, runtime vault contents, SQLite databases, archives, or LanceDB files. Required configuration includes `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_IDS`; LLM and embedding settings are optional and should degrade cleanly when unset.

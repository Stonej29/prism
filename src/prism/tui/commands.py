"""The TUI command vocabulary — the single source for the command bar and help.

Names mirror the Telegram bot's ``COMMANDS`` 1:1 (plus ``save``), so the
parity test can assert every bot command is reachable here.
"""
from __future__ import annotations

# (name, usage, description). Typed at the command bar as e.g. ``ask <question>``.
TUI_COMMANDS: list[tuple[str, str, str]] = [
    ("help", "help", "Show all commands"),
    ("save", "save <url>", "Save a URL (or just paste a URL)"),
    ("ask", "ask <question>", "Answer a question from your saved notes"),
    ("find", "find <query>", "Semantic search of your notes"),
    ("related", "related <query-or-id>", "Find notes related to a query or note id"),
    ("recent", "recent", "Browse recent notes"),
    ("inbox", "inbox", "Browse unreviewed notes (review queue)"),
    ("tags", "tags [tag]", "Browse tags, or notes for a tag"),
    ("more", "more <id>", "Show the full detail of a note"),
    ("idea", "idea [topic]", "Generate a project idea, then rate it"),
    ("ideas", "ideas", "Browse generated ideas with ratings"),
    ("proposals", "proposals", "Review graph maintenance proposals"),
    ("ingest", "ingest", "Pull configured feeds now"),
    ("traverse", "traverse", "Run graph maintenance now"),
    ("rename", "rename <id> <title>", "Rename a note"),
    ("status_set", "status_set <id> <status>", "Set a note's review status"),
    ("reprocess", "reprocess <id>", "Re-run LLM generation for a note"),
    ("reprocess_all", "reprocess_all", "Re-run LLM generation for every note"),
    ("repersonalize", "repersonalize <id>", "Re-run only personalization for a note"),
    ("retry_failed", "retry_failed [n]", "Retry failed LLM and embedding work"),
    ("delete", "delete <id>", "Delete a note (after confirmation)"),
    ("wipe_all", "wipe_all", "Wipe all notes, ideas, archives, and index"),
    ("reset_me", "reset_me <text>", "Replace the personal profile from text"),
    ("update_me", "update_me <text>", "Merge new text into the personal profile"),
    ("status", "status", "Show note, LLM, and index counts"),
]

COMMAND_NAMES: frozenset[str] = frozenset(name for name, _, _ in TUI_COMMANDS)


def help_markdown() -> str:
    lines = ["# Commands", "", "Type any of these in the command bar (`/` to focus it).", ""]
    lines += [f"- `{usage}` — {desc}" for _, usage, desc in TUI_COMMANDS]
    lines += [
        "",
        "## Keys",
        "- `1` `2` `3` `4` — notes / ideas / tags / proposals",
        "- `/` — focus command bar",
        "- `r` rate idea · `d` delete · `a`/`x` approve/reject proposal · `g` reprocess · `f` cycle status filter",
        "- `?` help · `q` quit",
    ]
    return "\n".join(lines)

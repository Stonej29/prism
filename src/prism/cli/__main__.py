"""`prism-cli` — scriptable terminal access to PRISM.

A thin argparse front-end over :class:`prism.cli_core.CliCore`. Every subcommand
maps to one facade method and prints plain text, so output pipes cleanly. The
full-screen interactive experience lives in `prism.tui`.
"""
from __future__ import annotations

import argparse
import sys

from prism.cli.render import (
    candidate_line,
    idea_line,
    note_detail,
    note_line,
    proposal_line,
)
from prism.cli_core import CliCore
from prism.config import load_settings
from prism.notes import NOTE_STATUSES


def _core() -> CliCore:
    return CliCore.from_settings(load_settings(require_telegram=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prism-cli", description="Terminal access to your PRISM knowledge base.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("save", help="Save a URL")
    p.add_argument("url")

    p = sub.add_parser("find", help="Semantic search of your notes")
    p.add_argument("query", nargs="+")
    p.add_argument("-n", "--limit", type=int, default=20)

    p = sub.add_parser("ask", help="Answer a question from your saved notes")
    p.add_argument("question", nargs="+")
    p.add_argument("-n", "--limit", type=int, default=6)

    p = sub.add_parser("related", help="Find notes related to a query or note id")
    p.add_argument("query", nargs="+")
    p.add_argument("-n", "--limit", type=int, default=20)

    p = sub.add_parser("recent", help="Browse recent notes")
    p.add_argument("-n", "--limit", type=int, default=10)
    p.add_argument("--status", choices=[*NOTE_STATUSES, "all"], default=None,
                   help="Filter by review status (default: hide archived)")

    p = sub.add_parser("tags", help="List tags, or notes for a tag")
    p.add_argument("tag", nargs="?")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--status", choices=[*NOTE_STATUSES, "all"], default=None,
                   help="Filter notes-for-a-tag by review status (default: hide archived)")

    p = sub.add_parser("more", help="Show the full detail of a note")
    p.add_argument("note_id")

    p = sub.add_parser("idea", help="Generate a project idea")
    p.add_argument("topic", nargs="*")

    sub.add_parser("ideas", help="Browse generated ideas").add_argument("-n", "--limit", type=int, default=10)

    p = sub.add_parser("rate", help="Rate an idea (1-5)")
    p.add_argument("idea_id")
    p.add_argument("rating", type=int)

    sub.add_parser("proposals", help="Review graph maintenance proposals")

    sub.add_parser("approve", help="Approve a proposal").add_argument("proposal_id")
    sub.add_parser("reject", help="Reject a proposal").add_argument("proposal_id")

    sub.add_parser("ingest", help="Pull configured feeds now")
    sub.add_parser("traverse", help="Run graph maintenance now")
    sub.add_parser("reembed", help="Re-embed notes whose index text changed")
    sub.add_parser("backup", help="Commit the vault and snapshot the SQLite DB")

    p = sub.add_parser("rename", help="Rename a note")
    p.add_argument("note_id")
    p.add_argument("title", nargs="+")

    p = sub.add_parser("set-status", help="Set review status for one or more notes")
    p.add_argument("status", choices=NOTE_STATUSES)
    p.add_argument("note_id", nargs="+")

    sub.add_parser("reprocess", help="Re-run LLM generation for a note").add_argument("note_id")
    sub.add_parser("retry-failed", help="Retry failed LLM and embedding work").add_argument(
        "-n", "--limit", type=int, default=25
    )

    p = sub.add_parser("delete", help="Delete a note or idea")
    p.add_argument("item_id")
    p.add_argument("--idea", action="store_true", help="Treat the id as an idea id")

    sub.add_parser("status", help="Show note, LLM, and index counts")

    sub.add_parser("reset-me", help="Replace the personal profile from text").add_argument("text", nargs="+")
    sub.add_parser("update-me", help="Merge new text into the personal profile").add_argument("text", nargs="+")

    sub.add_parser("wipe-all", help="Wipe all notes, ideas, archives, and index").add_argument(
        "--yes", action="store_true", help="Required confirmation"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    core = _core()
    handler = _HANDLERS[args.command]
    return handler(core, args) or 0


# --- handlers -------------------------------------------------------------
def _save(core: CliCore, args) -> int:
    result = core.save_url(args.url)
    if result.created:
        print(f"Saved [{result.record.note_id}] {result.record.title}")
    else:
        print(f"Duplicate ({result.duplicate_reason}): [{result.record.note_id}] {result.record.title}")
    return 0


def _find(core: CliCore, args) -> int:
    outcome = core.find(" ".join(args.query), args.limit)
    if not outcome.ok:
        print(outcome.message, file=sys.stderr)
        return 1
    for c in outcome.candidates:
        print(candidate_line(c))
    return 0


def _ask(core: CliCore, args) -> int:
    result = core.ask(" ".join(args.question), args.limit)
    if not result.ok:
        print(result.message, file=sys.stderr)
        return 1
    print(result.answer)
    if result.sources:
        print("\nSources:")
        for c in result.sources:
            print(f"  {candidate_line(c)}")
    return 0


def _related(core: CliCore, args) -> int:
    outcome = core.related(" ".join(args.query), args.limit)
    if not outcome.ok:
        print(outcome.message, file=sys.stderr)
        return 1
    for c in outcome.candidates:
        print(candidate_line(c))
    return 0


def _recent(core: CliCore, args) -> int:
    for record in core.recent_notes(args.limit, status=args.status):
        print(note_line(record))
    return 0


def _tags(core: CliCore, args) -> int:
    if args.tag:
        records = core.notes_by_tag(args.tag, args.limit, status=args.status)
        if not records:
            print(f"No notes tagged {args.tag!r}.")
        for record in records:
            print(note_line(record))
    else:
        for tag, count in core.tags():
            print(f"{count:4d}  {tag}")
    return 0


def _more(core: CliCore, args) -> int:
    record = core.note(args.note_id)
    if not record:
        print(f"No note found for {args.note_id}.", file=sys.stderr)
        return 1
    print(note_detail(record))
    return 0


def _idea(core: CliCore, args) -> int:
    topic = " ".join(args.topic) if args.topic else None
    result = core.generate_idea(topic)
    if result.record:
        print(f"[{result.record.idea_id}] {result.record.title}")
    print(result.message)
    return 0 if result.ok else 1


def _ideas(core: CliCore, args) -> int:
    for record in core.recent_ideas(args.limit):
        print(idea_line(record))
    return 0


def _rate(core: CliCore, args) -> int:
    if not 1 <= args.rating <= 5:
        print("Rating must be 1-5.", file=sys.stderr)
        return 1
    record = core.rate_idea(args.idea_id, args.rating)
    if not record:
        print(f"No idea found for {args.idea_id}.", file=sys.stderr)
        return 1
    print(f"Rated [{record.idea_id}] {record.title}: {args.rating}/5")
    return 0


def _proposals(core: CliCore, args) -> int:
    pending = core.pending_proposals()
    if not pending:
        print("No pending proposals.")
    for record in pending:
        print(proposal_line(record))
    return 0


def _approve(core: CliCore, args) -> int:
    return _proposal_action(core.approve_proposal(args.proposal_id))


def _reject(core: CliCore, args) -> int:
    return _proposal_action(core.reject_proposal(args.proposal_id))


def _proposal_action(result) -> int:
    print(result.message)
    return 0 if result.ok else 1


def _ingest(core: CliCore, args) -> int:
    result = core.ingest()
    if not result.ok:
        print(result.message, file=sys.stderr)
        return 1
    s = result.summary
    print(f"{s.feeds} feeds, {s.seen} seen, {s.created} created, {s.duplicates} duplicates, {s.failed} failed")
    for err in s.errors[:5]:
        print(f"  ! {err}", file=sys.stderr)
    return 0


def _traverse(core: CliCore, args) -> int:
    s = core.traverse()
    print(
        f"{s.notes} notes, {s.links_added} links added, {s.links_removed} removed, "
        f"{s.tags_merged} tags merged, {s.duplicates_proposed} merge proposals"
    )
    return 0


def _rename(core: CliCore, args) -> int:
    result = core.rename_note(args.note_id, " ".join(args.title))
    print(result.message)
    return 0 if result.ok else 1


def _set_status(core: CliCore, args) -> int:
    results = core.set_status_bulk(args.note_id, args.status)
    ok = True
    for result in results:
        print(result.message)
        ok = ok and result.ok
    return 0 if ok else 1


def _reembed(core: CliCore, args) -> int:
    s = core.reembed()
    print(f"{s.checked} checked, {s.stale} stale, {s.reindexed} reindexed, {s.failed} failed")
    return 0


def _backup(core: CliCore, args) -> int:
    s = core.backup()
    print(f"vault committed: {s.vault_committed}; snapshot: {s.snapshot_path or 'none'}; pruned {s.pruned}")
    for err in s.errors or []:
        print(f"  ! {err}", file=sys.stderr)
    return 0 if not s.errors else 1


def _reprocess(core: CliCore, args) -> int:
    result = core.reprocess(args.note_id)
    print(result.message)
    return 0 if result.ok else 1


def _retry_failed(core: CliCore, args) -> int:
    r = core.retry_failed(args.limit)
    print(f"total={r.total} retried={r.retried} repaired={r.repaired} failed={r.failed} skipped={r.skipped}")
    for msg in r.messages:
        print(f"  {msg}")
    return 0


def _delete(core: CliCore, args) -> int:
    if args.idea:
        record = core.delete_idea(args.item_id)
        if not record:
            print(f"No idea found for {args.item_id}.", file=sys.stderr)
            return 1
        print(f"Deleted idea [{record.idea_id}] {record.title}")
        return 0
    result = core.delete_note(args.item_id)
    print(result.message)
    return 0 if result.ok else 1


def _status(core: CliCore, args) -> int:
    info = core.status()
    s = info.stats
    print(f"Notes: {s.total}")
    print(f"LLM: {s.llm_generated} generated, {s.llm_failed} failed, {s.llm_skipped} skipped")
    print(f"Embeddings: {s.embedding_indexed} indexed, {s.embedding_failed} failed, {s.embedding_skipped} skipped")
    if info.index_configured:
        print(f"Index: {'empty' if info.index_empty else 'ready'}")
    else:
        print("Index: not configured")
    print(f"Pending proposals: {info.pending_proposals}")
    return 0


def _reset_me(core: CliCore, args) -> int:
    result = core.reset_profile(" ".join(args.text))
    print(result.message)
    return 0 if result.ok else 1


def _update_me(core: CliCore, args) -> int:
    result = core.update_profile(" ".join(args.text))
    print(result.message)
    return 0 if result.ok else 1


def _wipe_all(core: CliCore, args) -> int:
    if not args.yes:
        print("Refusing to wipe without --yes.", file=sys.stderr)
        return 1
    result = core.wipe_all()
    print(f"Wiped {result.notes} notes and {result.ideas} ideas.")
    return 0


_HANDLERS = {
    "save": _save,
    "find": _find,
    "ask": _ask,
    "related": _related,
    "recent": _recent,
    "tags": _tags,
    "more": _more,
    "idea": _idea,
    "ideas": _ideas,
    "rate": _rate,
    "proposals": _proposals,
    "approve": _approve,
    "reject": _reject,
    "ingest": _ingest,
    "traverse": _traverse,
    "reembed": _reembed,
    "backup": _backup,
    "rename": _rename,
    "set-status": _set_status,
    "reprocess": _reprocess,
    "retry-failed": _retry_failed,
    "delete": _delete,
    "status": _status,
    "reset-me": _reset_me,
    "update-me": _update_me,
    "wipe-all": _wipe_all,
}


if __name__ == "__main__":
    raise SystemExit(main())

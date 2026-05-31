"""The main three-pane Atlas screen: sidebar · detail · command bar.

All blocking work runs through ``@work(thread=True)`` workers via the generic
``_run`` helper, which catches exceptions and posts a :class:`WorkerResult` back
to the UI thread. Sidebar loads post a :class:`ListResult`.
"""
from __future__ import annotations

from collections.abc import Callable

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header

from prism.notes import extract_first_url
from prism.proposals import describe_proposal
from prism.tui import render
from prism.tui.commands import COMMAND_NAMES
from prism.tui.messages import ListEntry, ListResult, WorkerResult
from prism.tui.screens.confirm import ConfirmScreen, WipeConfirmScreen
from prism.tui.screens.help import HelpScreen
from prism.tui.screens.rating import RatingScreen
from prism.tui.widgets.command_bar import CommandBar
from prism.tui.widgets.detail import DetailPane
from prism.tui.widgets.sidebar import SourceList

LIST_LIMIT = 50


def _truncate(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class AtlasScreen(Screen):
    BINDINGS = [
        ("1", "set_mode('notes')", "Notes"),
        ("2", "set_mode('ideas')", "Ideas"),
        ("3", "set_mode('tags')", "Tags"),
        ("4", "set_mode('proposals')", "Proposals"),
        ("slash", "focus_command", "Command"),
        ("r", "rate_selected", "Rate"),
        ("d", "delete_selected", "Delete"),
        ("a", "approve_selected", "Approve"),
        ("x", "reject_selected", "Reject"),
        ("g", "reprocess_selected", "Reprocess"),
        ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected: ListEntry | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield SourceList(id="sidebar")
            yield DetailPane(id="detail")
        yield CommandBar(id="commandbar")
        yield Footer()

    # Convenience accessors -------------------------------------------------
    @property
    def core(self):
        return self.app.core  # type: ignore[attr-defined]

    @property
    def detail(self) -> DetailPane:
        return self.query_one("#detail", DetailPane)

    @property
    def sidebar(self) -> SourceList:
        return self.query_one("#sidebar", SourceList)

    @property
    def bar(self) -> CommandBar:
        return self.query_one("#commandbar", CommandBar)

    def set_status(self, text: str) -> None:
        self.bar.set_status(text)

    # Actions (key bindings) ------------------------------------------------
    def action_set_mode(self, mode: str) -> None:
        self.sidebar.mode = mode

    def action_focus_command(self) -> None:
        self.bar.focus_input()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_rate_selected(self) -> None:
        entry = self._require("idea")
        if not entry:
            return

        def after(rating: int | None) -> None:
            if rating is not None:
                self.set_status(f"Rating {entry.entry_id}…")
                self._run(lambda: self._op_rate(entry.entry_id, rating))

        self.app.push_screen(RatingScreen(entry.label), after)

    def action_delete_selected(self) -> None:
        entry = self.selected
        if entry is None or entry.kind not in {"note", "idea"}:
            self.set_status("Select a note or idea to delete.")
            return

        def after(confirmed: bool) -> None:
            if confirmed:
                self.set_status(f"Deleting {entry.entry_id}…")
                if entry.kind == "idea":
                    self._run(lambda: self._op_delete_idea(entry.entry_id))
                else:
                    self._run(lambda: self._op_delete_note(entry.entry_id))

        self.app.push_screen(ConfirmScreen(f"Delete {entry.kind} “{_truncate(entry.label)}”?"), after)

    def action_approve_selected(self) -> None:
        entry = self._require("proposal")
        if entry:
            self.set_status(f"Approving {entry.entry_id}…")
            self._run(lambda: self._op_proposal(entry.entry_id, approve=True))

    def action_reject_selected(self) -> None:
        entry = self._require("proposal")
        if entry:
            self.set_status(f"Rejecting {entry.entry_id}…")
            self._run(lambda: self._op_proposal(entry.entry_id, approve=False))

    def action_reprocess_selected(self) -> None:
        entry = self._require("note")
        if entry:
            self.set_status(f"Reprocessing {entry.entry_id}…")
            self._run(lambda: self._op_reprocess(entry.entry_id))

    def _require(self, kind: str) -> ListEntry | None:
        if self.selected is None or self.selected.kind != kind:
            self.set_status(f"Select a {kind} first.")
            return None
        return self.selected

    # Selection -------------------------------------------------------------
    def on_list_view_selected(self, event) -> None:  # textual ListView.Selected
        entry = getattr(event.item, "entry", None)
        if entry is None:
            return
        self.selected = entry
        if entry.kind == "note":
            self.detail.show(render.note_markdown(entry.data))
        elif entry.kind == "idea":
            self.detail.show(render.idea_markdown(entry.data))
        elif entry.kind == "proposal":
            self.detail.show(render.proposal_markdown(entry.data))
        elif entry.kind == "tag":
            self.set_status(f"Loading #{entry.entry_id}…")
            self.load_tag_notes(entry.entry_id)

    # Command bar -----------------------------------------------------------
    def on_input_submitted(self, event) -> None:  # textual Input.Submitted
        raw = event.value.strip()
        self.bar.clear_input()
        if raw:
            self.dispatch_command(raw)

    def dispatch_command(self, raw: str) -> None:
        first = raw.split(maxsplit=1)[0].lower()
        rest = raw[len(raw.split(maxsplit=1)[0]):].strip()
        if first not in COMMAND_NAMES:
            url = extract_first_url(raw)
            if url:
                self.set_status(f"Saving {url}…")
                self._run(lambda: self._op_save(url))
            else:
                self.set_status(f"Unknown command: {first} — type 'help'.")
            return

        if first == "help":
            self.action_help()
        elif first == "save":
            self._dispatch_save(rest)
        elif first == "ask":
            self._dispatch_blocking(rest, "Ask a question.", lambda q: self._op_ask(q), "Asking…")
        elif first == "find":
            self._dispatch_blocking(rest, "Enter a search query.", lambda q: self._op_find(q), "Searching…")
        elif first == "related":
            self._dispatch_blocking(rest, "Enter a query or note id.", lambda q: self._op_related(q), "Searching…")
        elif first == "idea":
            self.set_status("Generating idea…")
            topic = rest or None
            self._run(lambda: self._op_idea(topic))
        elif first == "more":
            self._dispatch_blocking(rest, "Usage: more <id>", lambda q: self._op_more(q), "Loading…")
        elif first == "recent":
            self.sidebar.mode = "notes"
        elif first == "ideas":
            self.sidebar.mode = "ideas"
        elif first == "proposals":
            self.sidebar.mode = "proposals"
        elif first == "tags":
            if rest:
                self.set_status(f"Loading #{rest}…")
                self.load_tag_notes(rest)
            else:
                self.sidebar.mode = "tags"
        elif first == "ingest":
            self.set_status("Ingesting feeds…")
            self._run(self._op_ingest)
        elif first == "traverse":
            self.set_status("Running graph maintenance…")
            self._run(self._op_traverse)
        elif first == "rename":
            self._dispatch_rename(rest)
        elif first == "status_set":
            self._dispatch_status_set(rest)
        elif first == "reprocess":
            self._dispatch_blocking(rest, "Usage: reprocess <id>", lambda q: self._op_reprocess(q), "Reprocessing…")
        elif first == "retry_failed":
            n = int(rest) if rest.isdigit() else 25
            self.set_status("Retrying failed work…")
            self._run(lambda: self._op_retry(n))
        elif first == "delete":
            self._dispatch_delete(rest)
        elif first == "wipe_all":
            self._dispatch_wipe()
        elif first == "reset_me":
            self._dispatch_blocking(rest, "Add profile text.", lambda t: self._op_profile(t, "reset"), "Updating profile…")
        elif first == "update_me":
            self._dispatch_blocking(rest, "Add profile text.", lambda t: self._op_profile(t, "update"), "Updating profile…")
        elif first == "status":
            self.set_status("Loading status…")
            self._run(self._op_status)

    def _dispatch_blocking(self, arg: str, empty_msg: str, op: Callable[[str], WorkerResult], busy: str) -> None:
        if not arg:
            self.set_status(empty_msg)
            return
        self.set_status(busy)
        self._run(lambda: op(arg))

    def _dispatch_save(self, rest: str) -> None:
        url = extract_first_url(rest) or rest
        if not url:
            self.set_status("Usage: save <url>")
            return
        self.set_status(f"Saving {url}…")
        self._run(lambda: self._op_save(url))

    def _dispatch_rename(self, rest: str) -> None:
        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            self.set_status("Usage: rename <id> <title>")
            return
        note_id, title = parts[0], parts[1]
        self.set_status(f"Renaming {note_id}…")
        self._run(lambda: self._op_rename(note_id, title))

    def _dispatch_status_set(self, rest: str) -> None:
        parts = rest.split()
        if len(parts) < 2:
            self.set_status("Usage: status_set <id> <status>")
            return
        note_id, status = parts[0], parts[1]
        self.set_status(f"Setting status of {note_id}…")
        self._run(lambda: self._op_status_set(note_id, status))

    def _dispatch_delete(self, rest: str) -> None:
        if not rest:
            self.set_status("Usage: delete <id>")
            return
        note_id = rest.split()[0]

        def after(confirmed: bool) -> None:
            if confirmed:
                self.set_status(f"Deleting {note_id}…")
                self._run(lambda: self._op_delete_note(note_id))

        self.app.push_screen(ConfirmScreen(f"Delete note {note_id}?"), after)

    def _dispatch_wipe(self) -> None:
        def after(confirmed: bool) -> None:
            if confirmed:
                self.set_status("Wiping everything…")
                self._run(self._op_wipe)

        self.app.push_screen(WipeConfirmScreen(), after)

    # Generic worker --------------------------------------------------------
    @work(thread=True)
    def _run(self, fn: Callable[[], WorkerResult]) -> None:
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - surface to status line
            result = WorkerResult(status=f"Error: {type(exc).__name__}: {exc}")
        self.post_message(result)

    # Operations (run inside _run, on a worker thread) ---------------------
    def _op_save(self, url: str) -> WorkerResult:
        r = self.core.save_url(url)
        status = f"Saved: {r.record.title}" if r.created else f"Duplicate ({r.duplicate_reason}): {r.record.title}"
        return WorkerResult(status, render.note_markdown(r.record), refresh=True)

    def _op_ask(self, q: str) -> WorkerResult:
        r = self.core.ask(q)
        if r.ok:
            return WorkerResult("", render.ask_markdown(q, r.answer, r.sources))
        return WorkerResult(r.message)

    def _op_find(self, q: str) -> WorkerResult:
        r = self.core.find(q)
        if r.ok:
            return WorkerResult(f"{len(r.candidates)} results", render.candidates_markdown(f"find: {q}", r.candidates))
        return WorkerResult(r.message)

    def _op_related(self, q: str) -> WorkerResult:
        r = self.core.related(q)
        if r.ok:
            return WorkerResult(f"{len(r.candidates)} results", render.candidates_markdown(f"related: {q}", r.candidates))
        return WorkerResult(r.message)

    def _op_idea(self, topic: str | None) -> WorkerResult:
        r = self.core.generate_idea(topic)
        detail = render.idea_markdown(r.record) if r.record else None
        return WorkerResult(r.message, detail, refresh=True)

    def _op_more(self, note_id: str) -> WorkerResult:
        record = self.core.note(note_id)
        if not record:
            return WorkerResult(f"No note found for {note_id}.")
        return WorkerResult("", render.note_markdown(record))

    def _op_rename(self, note_id: str, title: str) -> WorkerResult:
        r = self.core.rename_note(note_id, title)
        detail = render.note_markdown(r.record) if r.record else None
        return WorkerResult(r.message, detail, refresh=True)

    def _op_status_set(self, note_id: str, status: str) -> WorkerResult:
        r = self.core.set_status(note_id, status)
        detail = render.note_markdown(r.record) if r.record else None
        return WorkerResult(r.message, detail, refresh=True)

    def _op_reprocess(self, note_id: str) -> WorkerResult:
        r = self.core.reprocess(note_id)
        detail = render.note_markdown(r.record) if r.record else None
        return WorkerResult(r.message, detail, refresh=True)

    def _op_retry(self, n: int) -> WorkerResult:
        r = self.core.retry_failed(n)
        return WorkerResult(
            f"retried {r.retried}, repaired {r.repaired}, failed {r.failed}, skipped {r.skipped}", refresh=True
        )

    def _op_ingest(self) -> WorkerResult:
        r = self.core.ingest()
        if not r.ok:
            return WorkerResult(r.message)
        s = r.summary
        return WorkerResult(
            f"{s.feeds} feeds · {s.created} created · {s.duplicates} dup · {s.failed} failed", refresh=True
        )

    def _op_traverse(self) -> WorkerResult:
        s = self.core.traverse()
        return WorkerResult(
            f"{s.notes} notes · {s.links_added} links+ · {s.tags_merged} tags merged · "
            f"{s.duplicates_proposed} proposals",
            refresh=True,
        )

    def _op_profile(self, text: str, mode: str) -> WorkerResult:
        r = self.core.update_profile(text) if mode == "update" else self.core.reset_profile(text)
        return WorkerResult(r.message)

    def _op_status(self) -> WorkerResult:
        return WorkerResult("", render.status_markdown(self.core.status()))

    def _op_delete_note(self, note_id: str) -> WorkerResult:
        r = self.core.delete_note(note_id)
        return WorkerResult(r.message, refresh=True)

    def _op_delete_idea(self, idea_id: str) -> WorkerResult:
        record = self.core.delete_idea(idea_id)
        msg = f"Deleted idea {record.title}" if record else f"No idea found for {idea_id}."
        return WorkerResult(msg, refresh=True)

    def _op_rate(self, idea_id: str, rating: int) -> WorkerResult:
        record = self.core.rate_idea(idea_id, rating)
        msg = f"Rated {record.title}: {rating}/5" if record else f"No idea found for {idea_id}."
        return WorkerResult(msg, refresh=True)

    def _op_proposal(self, proposal_id: str, *, approve: bool) -> WorkerResult:
        r = self.core.approve_proposal(proposal_id) if approve else self.core.reject_proposal(proposal_id)
        return WorkerResult(r.message, refresh=True)

    def _op_wipe(self) -> WorkerResult:
        r = self.core.wipe_all()
        return WorkerResult(f"Wiped {r.notes} notes and {r.ideas} ideas.", refresh=True)

    # Sidebar list loading --------------------------------------------------
    @work(thread=True, exclusive=True, group="list")
    def load_list(self, mode: str) -> None:
        try:
            header, items = self._build_list(mode)
        except Exception as exc:  # noqa: BLE001
            self.post_message(WorkerResult(f"List error: {type(exc).__name__}: {exc}"))
            return
        self.post_message(ListResult(mode, header, items))

    @work(thread=True, exclusive=True, group="list")
    def load_tag_notes(self, tag: str) -> None:
        try:
            records = self.core.notes_by_tag(tag, LIST_LIMIT)
            items = [ListEntry(r.note_id, _truncate(r.title), "note", r) for r in records]
        except Exception as exc:  # noqa: BLE001
            self.post_message(WorkerResult(f"List error: {type(exc).__name__}: {exc}"))
            return
        self.post_message(ListResult("tags", f"#{tag} ({len(items)})", items))

    def _build_list(self, mode: str) -> tuple[str, list[ListEntry]]:
        if mode == "ideas":
            ideas = self.core.recent_ideas(LIST_LIMIT)
            items = [
                ListEntry(i.idea_id, f"{_truncate(i.title, 50)}  ({i.rating if i.rating is not None else '–'})", "idea", i)
                for i in ideas
            ]
            return f"Ideas ({len(items)})", items
        if mode == "tags":
            tags = self.core.tags()
            items = [ListEntry(tag, f"{tag}  ({count})", "tag", tag) for tag, count in tags]
            return f"Tags ({len(items)})", items
        if mode == "proposals":
            proposals = self.core.pending_proposals()
            items = [ListEntry(p.proposal_id, _truncate(describe_proposal(p)), "proposal", p) for p in proposals]
            return f"Proposals ({len(items)})", items
        notes = self.core.recent_notes(LIST_LIMIT)
        items = [ListEntry(n.note_id, _truncate(n.title), "note", n) for n in notes]
        return f"Notes ({len(items)})", items

    # Result handlers (UI thread) ------------------------------------------
    def on_list_result(self, message: ListResult) -> None:
        self.sidebar.populate(message.header, message.items)

    def on_worker_result(self, message: WorkerResult) -> None:
        if message.status:
            self.set_status(message.status)
        if message.detail is not None:
            self.detail.show(message.detail)
        if message.refresh:
            self.sidebar.reload()

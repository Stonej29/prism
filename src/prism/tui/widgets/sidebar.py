"""Left pane: a mode header plus a list of notes / ideas / tags / proposals."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Label, ListItem, ListView

from prism.tui.messages import ListEntry

MODES = ("notes", "ideas", "tags", "proposals")
MODE_LABELS = {"notes": "Notes", "ideas": "Ideas", "tags": "Tags", "proposals": "Proposals"}


class EntryItem(ListItem):
    """A ListItem that carries the underlying record."""

    def __init__(self, entry: ListEntry) -> None:
        super().__init__(Label(entry.label))
        self.entry = entry


class SourceList(Vertical):
    """Switchable list. Changing ``mode`` asks the app to (re)load the list."""

    mode: reactive[str] = reactive("notes")

    def compose(self) -> ComposeResult:
        yield Label("Notes", id="sidebar-header")
        yield ListView(id="sidebar-list")

    @property
    def list_view(self) -> ListView:
        return self.query_one("#sidebar-list", ListView)

    def on_mount(self) -> None:
        self.reload()

    def watch_mode(self, mode: str) -> None:
        if self.is_mounted:
            self.reload()

    def reload(self) -> None:
        """Trigger a (threaded) load of the current mode via the screen."""
        self.screen.load_list(self.mode)  # type: ignore[attr-defined]

    def populate(self, header: str, items: list[ListEntry]) -> None:
        self.query_one("#sidebar-header", Label).update(header)
        view = self.list_view
        view.clear()
        for entry in items:
            view.append(EntryItem(entry))

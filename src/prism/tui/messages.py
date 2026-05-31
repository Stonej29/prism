"""Typed messages passed between TUI workers and the UI.

Threaded workers on :class:`~prism.tui.app.PrismApp` compute results off the UI
thread and ``post_message`` one of these back; the app's ``on_*`` handlers then
update the widgets on the event loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.message import Message


@dataclass
class ListEntry:
    """One row in the sidebar list."""

    entry_id: str
    label: str
    kind: str  # "note" | "idea" | "tag" | "proposal"
    data: Any = None  # the underlying frozen record (or tag string)


class ListResult(Message):
    """A sidebar list finished loading."""

    def __init__(self, mode: str, header: str, items: list[ListEntry]) -> None:
        self.mode = mode
        self.header = header
        self.items = items
        super().__init__()


class WorkerResult(Message):
    """A blocking operation finished.

    ``detail`` (Markdown) replaces the detail pane when present; ``refresh``
    asks the sidebar to reload its current list.
    """

    def __init__(self, status: str, detail: str | None = None, refresh: bool = False) -> None:
        self.status = status
        self.detail = detail
        self.refresh = refresh
        super().__init__()

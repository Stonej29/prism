"""Bottom command bar: an Input plus a one-line status label."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label


class CommandBar(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_status = ""

    def compose(self) -> ComposeResult:
        yield Label("", id="status-line")
        yield Input(placeholder="Type a command (help) or paste a URL…", id="command-input")

    def set_status(self, text: str) -> None:
        self.last_status = text
        self.query_one("#status-line", Label).update(text)

    def focus_input(self) -> None:
        self.query_one("#command-input", Input).focus()

    def clear_input(self) -> None:
        self.query_one("#command-input", Input).value = ""

"""Modal help screen listing every command and key binding."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown

from prism.tui.commands import help_markdown


class HelpScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_help", "Close"), ("question_mark", "dismiss_help", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Markdown(help_markdown())

    def action_dismiss_help(self) -> None:
        self.dismiss(None)

"""Modal confirmation screens for destructive actions."""
from __future__ import annotations

import secrets

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class ConfirmScreen(ModalScreen[bool]):
    """Yes/Cancel confirmation. Dismisses with ``True`` on confirm."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._prompt, id="dialog-prompt")
            with Horizontal(id="dialog-buttons"):
                yield Button("Delete", variant="error", id="confirm")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class WipeConfirmScreen(ModalScreen[bool]):
    """Wipe-all guard: the user must type a shown code before confirming."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._code = secrets.token_hex(3)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(
                f"This wipes ALL notes, ideas, archives and the index.\n"
                f"Type [b]{self._code}[/b] to confirm.",
                id="dialog-prompt",
            )
            yield Input(placeholder="confirmation code", id="wipe-code")
            with Horizontal(id="dialog-buttons"):
                yield Button("Wipe everything", variant="error", id="confirm")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return
        typed = self.query_one("#wipe-code", Input).value.strip()
        self.dismiss(typed == self._code)

    def action_cancel(self) -> None:
        self.dismiss(False)

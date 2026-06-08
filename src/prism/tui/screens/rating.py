"""Modal idea-rating screen (1-5)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class RatingScreen(ModalScreen[int]):
    """Pick a 1-5 rating. Dismisses with the chosen int, or ``None`` on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Rate: {self._title}", id="dialog-prompt")
            with Horizontal(id="dialog-buttons"):
                for n in range(1, 6):
                    yield Button(f"{n}", id=f"rate-{n}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        assert event.button.id is not None
        self.dismiss(int(event.button.id.split("-")[1]))

    def action_cancel(self) -> None:
        self.dismiss(None)

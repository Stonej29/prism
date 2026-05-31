"""The PRISM Textual application."""
from __future__ import annotations

from pathlib import Path

from textual.app import App

from prism.cli_core import CliCore
from prism.tui.screens.main_screen import AtlasScreen


class PrismApp(App):
    CSS_PATH = Path(__file__).parent / "styles.tcss"
    TITLE = "PRISM"
    SUB_TITLE = "research knowledge base"

    def __init__(self, core: CliCore) -> None:
        super().__init__()
        self.core = core

    def on_mount(self) -> None:
        self.push_screen(AtlasScreen())

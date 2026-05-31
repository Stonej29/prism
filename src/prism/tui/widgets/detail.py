"""Right pane: a scrollable Markdown view of the selected item or result."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Markdown

WELCOME = (
    "# PRISM\n\n"
    "Your research knowledge base.\n\n"
    "- `1` `2` `3` `4` switch the list between notes, ideas, tags, proposals\n"
    "- press `/` then type a command (e.g. `find diffusion models`)\n"
    "- paste a URL to save it\n"
    "- `?` for all commands\n"
)


class DetailPane(VerticalScroll):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_markdown = WELCOME

    def compose(self) -> ComposeResult:
        yield Markdown(WELCOME, id="detail-md")

    def show(self, markdown: str) -> None:
        self.last_markdown = markdown
        self.query_one("#detail-md", Markdown).update(markdown)
        self.scroll_home(animate=False)

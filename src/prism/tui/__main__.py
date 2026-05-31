"""Entry point for the PRISM TUI (`prism-tui`)."""
from __future__ import annotations

from prism.cli_core import CliCore
from prism.config import load_settings
from prism.tui.app import PrismApp


def main() -> None:
    core = CliCore.from_settings(load_settings(require_telegram=False))
    PrismApp(core).run()


if __name__ == "__main__":
    main()

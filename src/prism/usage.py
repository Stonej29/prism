"""Process-wide token-usage sink.

The LLM and embedding clients report token usage through `record_usage()`. A host
process (web/bot/worker) may install a sink via `set_usage_sink()` to persist the
totals (e.g. into SQLite). It is a no-op until a sink is installed, so the library
code stays decoupled from the database and tests don't need one.
"""
from __future__ import annotations

import logging
from typing import Callable

LOGGER = logging.getLogger("prism.usage")

# (kind, prompt_tokens, completion_tokens, total_tokens); kind is "llm" or "embedding".
UsageSink = Callable[[str, int, int, int], None]

_sink: UsageSink | None = None


def set_usage_sink(sink: UsageSink | None) -> None:
    global _sink
    _sink = sink


def _coerce(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def record_usage(kind: str, prompt_tokens: object, completion_tokens: object, total_tokens: object) -> None:
    """Report one call's token usage to the installed sink (no-op if none)."""
    sink = _sink
    if sink is None:
        return
    try:
        sink(kind, _coerce(prompt_tokens), _coerce(completion_tokens), _coerce(total_tokens))
    except Exception:  # never let usage tracking break a request
        LOGGER.debug("usage sink failed", exc_info=True)

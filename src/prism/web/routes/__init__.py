"""API route modules, all mounted under /api by the app factory."""
from __future__ import annotations

from prism.db import NoteRecord, PrismDatabase

_PAGE = 200


def gather_all_notes(database: PrismDatabase) -> list[NoteRecord]:
    """Page through every note (corpus is small: tens, not millions).

    Uses status="all" so callers like the graph see the full corpus including
    archived notes; the notes-list endpoint applies its own status filter.
    """
    records: list[NoteRecord] = []
    offset = 0
    while True:
        page = database.list_recent_notes(_PAGE, offset, status="all")
        if not page:
            break
        records.extend(page)
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return records

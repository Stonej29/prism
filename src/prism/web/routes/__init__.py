"""API route modules, all mounted under /api by the app factory."""
from __future__ import annotations

from prism.db import NoteRecord, PrismDatabase
from prism.notes import scores_for_record

_PAGE = 200


def filter_notes(
    records: list[NoteRecord],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    min_score: float | None = None,
) -> list[NoteRecord]:
    """Apply optional date-range and minimum-overall-score filters in Python.

    `date_from`/`date_to` are YYYY-MM-DD and compared against the date portion of
    each note's ISO `date_saved` (string compare is valid for ISO dates). Notes
    without a numeric overall score are excluded when `min_score` is set.
    """
    out = records
    if date_from:
        out = [r for r in out if (r.date_saved or "")[:10] >= date_from]
    if date_to:
        out = [r for r in out if (r.date_saved or "")[:10] <= date_to]
    if min_score is not None:
        def _ok(r: NoteRecord) -> bool:
            overall = scores_for_record(r).get("overall")
            return isinstance(overall, (int, float)) and float(overall) >= min_score
        out = [r for r in out if _ok(r)]
    return out


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

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

_ACTIVITY_LIMIT = 200
_LOCK = Lock()
_ENTRIES: deque[dict[str, Any]] = deque(maxlen=_ACTIVITY_LIMIT)
_NEXT_ID = 0


def log_activity(action: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    global _NEXT_ID
    with _LOCK:
        _NEXT_ID += 1
        entry = {
            "id": _NEXT_ID,
            "at": _now(),
            "action": action,
            "status": status,
            "message": message[:500],
            "details": {k: v for k, v in details.items() if v is not None},
        }
        _ENTRIES.append(entry)
        return dict(entry)


def activity_entries(limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(200, int(limit)))
    with _LOCK:
        return [dict(entry) for entry in list(_ENTRIES)[-limit:]][::-1]


def clear_activity() -> None:
    global _NEXT_ID
    with _LOCK:
        _ENTRIES.clear()
        _NEXT_ID = 0


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

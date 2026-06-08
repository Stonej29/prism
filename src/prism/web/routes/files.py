from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from prism.config import Settings
from prism.web.deps import get_settings

router = APIRouter(tags=["files"])


def _resolve(base: Path, rel: str) -> Path:
    """Resolve base/rel, rejecting anything that escapes base (path traversal)."""
    target = (base / rel).resolve()
    root = base.resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="Path escapes root")
    return target


@router.get("/file")
def get_file(
    path: str = Query(...),
    root: str = Query("vault"),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    if root == "archive":
        base = settings.archive_path
    elif root == "vault":
        base = settings.vault_path
    else:
        raise HTTPException(status_code=400, detail="Unknown root")
    target = _resolve(base, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # inline disposition so PDFs/images render in the viewer instead of downloading
    return FileResponse(target, filename=target.name, content_disposition_type="inline")

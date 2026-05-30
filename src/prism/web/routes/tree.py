from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from prism.config import Settings
from prism.db import PrismDatabase
from prism.web.deps import get_db, get_settings
from prism.web.routes import gather_all_notes

router = APIRouter(tags=["tree"])

_SKIP = {".git", ".obsidian", ".trash"}


def _build_node(path: Path, vault: Path, notes: dict[str, str], ideas: dict[str, str]) -> dict[str, Any] | None:
    name = path.name
    if name.startswith(".") or name in _SKIP:
        return None
    rel = str(path.relative_to(vault))
    if path.is_dir():
        children: list[dict[str, Any]] = []
        for child in path.iterdir():
            node = _build_node(child, vault, notes, ideas)
            if node:
                children.append(node)
        # folders first, then files; reverse-alpha so newest date-prefixed notes sort up
        children.sort(key=lambda n: (n["type"] != "dir", _rev_key(n["name"])))
        return {"name": name, "path": rel, "type": "dir", "children": children}
    return {
        "name": name,
        "path": rel,
        "type": "file",
        "note_id": notes.get(rel),
        "idea_id": ideas.get(rel),
    }


def _rev_key(name: str) -> str:
    # invert characters so a normal ascending sort yields reverse-alphabetical order
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in name)


@router.get("/tree")
def get_tree(db: PrismDatabase = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    vault: Path = settings.vault_path
    notes = {r.note_path: r.note_id for r in gather_all_notes(db)}
    ideas = {r.note_path: r.idea_id for r in db.list_recent_ideas(500) if r.note_path}
    if not vault.exists():
        return {"name": vault.name, "path": "", "type": "dir", "children": []}
    root = _build_node(vault, vault, notes, ideas)
    return root or {"name": vault.name, "path": "", "type": "dir", "children": []}

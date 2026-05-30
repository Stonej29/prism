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


def _rev_key(name: str) -> str:
    # invert chars so a normal ascending sort yields reverse-alphabetical order
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in name)


def _sort_children(children: list[dict[str, Any]]) -> None:
    children.sort(key=lambda n: (n["type"] != "dir", _rev_key(n["name"])))


def _build_vault_node(path: Path, vault: Path, notes: dict[str, str], ideas: dict[str, str]) -> dict[str, Any] | None:
    name = path.name
    if name.startswith(".") or name in _SKIP:
        return None
    rel = str(path.relative_to(vault))
    if path.is_dir():
        children: list[dict[str, Any]] = []
        for child in path.iterdir():
            node = _build_vault_node(child, vault, notes, ideas)
            if node:
                children.append(node)
        _sort_children(children)
        return {"name": name, "path": rel, "type": "dir", "children": children}
    return {
        "name": name,
        "path": rel,
        "type": "file",
        "root": "vault",
        "note_id": notes.get(rel),
        "idea_id": ideas.get(rel),
    }


def _build_archive(archive: Path, titles: dict[str, str]) -> dict[str, Any]:
    folders: list[dict[str, Any]] = []
    if archive.exists():
        for sub in archive.iterdir():
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            files: list[dict[str, Any]] = []
            for f in sub.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    files.append({
                        "name": f.name,
                        "path": str(f.relative_to(archive)),
                        "type": "file",
                        "root": "archive",
                    })
            _sort_children(files)
            folders.append({
                "name": titles.get(sub.name, sub.name),
                "path": sub.name,
                "type": "dir",
                "children": files,
            })
    _sort_children(folders)
    return {"name": "Archive", "path": "", "type": "dir", "children": folders}


@router.get("/tree")
def get_tree(db: PrismDatabase = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    vault: Path = settings.vault_path
    records = gather_all_notes(db)
    notes = {r.note_path: r.note_id for r in records}
    titles = {r.note_id: r.title for r in records}
    ideas = {r.note_path: r.idea_id for r in db.list_recent_ideas(500) if r.note_path}

    children: list[dict[str, Any]] = []
    if vault.exists():
        root = _build_vault_node(vault, vault, notes, ideas)
        if root:
            children.extend(root.get("children", []))
    children.append(_build_archive(settings.archive_path, titles))
    return {"name": "vault", "path": "", "type": "dir", "children": children}

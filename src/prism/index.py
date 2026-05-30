from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prism.db import NoteRecord, PrismDatabase
from prism.embedding import EmbeddingClient, EmbeddingConfig

TABLE_NAME = "notes"
# Build an approximate-nearest-neighbour index once the corpus is large enough to
# benefit; below this, LanceDB's exact flat scan is faster and create_index errors.
ANN_INDEX_MIN_ROWS = 256


@dataclass(frozen=True)
class RelatedCandidate:
    note_id: str
    title: str
    summary: str
    note_path: str
    source_url: str
    tags: list[str]
    score: float

    def to_llm_dict(self) -> dict[str, Any]:
        return {
            "id": self.note_id,
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "path": self.note_path,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class IndexResult:
    status: str
    error: str | None = None
    embedded_at: str | None = None
    model: str | None = None
    dimensions: int | None = None
    text_hash: str | None = None


class NoteIndexer:
    def __init__(self, lancedb_path: Path, embedding_config: EmbeddingConfig) -> None:
        self.lancedb_path = lancedb_path
        self.embedding_config = embedding_config
        self.embedding_client = EmbeddingClient(embedding_config)

    @property
    def is_configured(self) -> bool:
        return self.embedding_config.is_configured

    def index_record(self, record: NoteRecord, database: PrismDatabase | None = None) -> IndexResult:
        if not self.is_configured:
            result = IndexResult(status="skipped", error="EMBEDDING_API_KEY or EMBEDDING_MODEL is not configured")
            if database:
                database.update_embedding_metadata(record.note_id, embedding_status=result.status, embedding_error=result.error)
            return result

        text = canonical_index_text(record)
        try:
            embedding = self.embedding_client.embed(text)
            text_hash = hash_text(text)
            embedded_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            self._upsert(record, embedding.vector, embedding.model, text_hash, embedded_at)
            result = IndexResult(
                status="indexed",
                embedded_at=embedded_at,
                model=embedding.model,
                dimensions=embedding.dimensions,
                text_hash=text_hash,
            )
        except Exception as exc:
            result = IndexResult(status="failed", error=f"{type(exc).__name__}: {exc}"[:1000])

        if database:
            database.update_embedding_metadata(
                record.note_id,
                embedding_status=result.status,
                embedding_error=result.error,
                embedded_at=result.embedded_at,
                embedding_model=result.model,
                embedding_dimensions=result.dimensions,
                embedding_text_hash=result.text_hash,
            )
        return result

    def search_text(self, query: str, *, limit: int = 5, exclude_note_id: str | None = None) -> list[RelatedCandidate]:
        if not self.is_configured:
            raise RuntimeError("EMBEDDING_API_KEY and EMBEDDING_MODEL are not configured")
        if not query.strip():
            raise ValueError("query must not be empty")
        embedding = self.embedding_client.embed(query)
        return self._search_vector(embedding.vector, limit=limit, exclude_note_id=exclude_note_id)

    def search_related(self, record: NoteRecord, *, limit: int = 10) -> list[RelatedCandidate]:
        return self.search_text(canonical_index_text(record), limit=limit, exclude_note_id=record.note_id)

    def all_vectors(self) -> dict[str, list[float]]:
        """Return {note_id: vector} for every indexed note (used for clustering)."""
        table = self._open_table()
        if table is None:
            return {}
        try:
            rows = table.to_arrow().to_pylist()
        except Exception:
            return {}
        out: dict[str, list[float]] = {}
        for row in rows:
            nid = row.get("note_id")
            vec = row.get("vector")
            if nid is None or vec is None:
                continue
            try:
                out[str(nid)] = [float(x) for x in vec]
            except (TypeError, ValueError):
                continue
        return out

    def ensure_ann_index(self) -> bool:
        """Create a vector ANN index once the table is large enough. Idempotent and non-fatal.

        Below ANN_INDEX_MIN_ROWS the exact flat scan is faster, and create_index
        would fail for lack of training data. Any failure is swallowed: search
        still works via flat scan.
        """
        table = self._open_table()
        if table is None:
            return False
        try:
            if int(table.count_rows()) < ANN_INDEX_MIN_ROWS:
                return False
        except Exception:
            return False
        try:
            if table.list_indices():
                return False
        except Exception:
            pass
        try:
            table.create_index(metric="cosine", vector_column_name="vector")
            return True
        except Exception:
            return False

    def index_is_empty(self) -> bool:
        table = self._open_table()
        if table is None:
            return True
        try:
            return int(table.count_rows()) == 0
        except Exception:
            return False

    def delete_record(self, note_id: str) -> None:
        table = self._open_table()
        if table is None:
            return
        escaped = note_id.replace("'", "''")
        table.delete(f"note_id = '{escaped}'")

    def clear(self) -> None:
        table = self._open_table()
        if table is None:
            return
        table.delete("note_id IS NOT NULL")

    def _upsert(self, record: NoteRecord, vector: list[float], model: str, text_hash: str, embedded_at: str) -> None:
        db = self._connect()
        row = {
            "note_id": record.note_id,
            "title": record.title,
            "summary": record.summary,
            "note_path": record.note_path,
            "source_url": record.source_url,
            "tags_json": json.dumps(tags_for_record(record), ensure_ascii=True),
            "embedding_model": model,
            "embedding_text_hash": text_hash,
            "embedded_at": embedded_at,
            "vector": vector,
        }
        table = self._open_table(db)
        if table is None:
            db.create_table(TABLE_NAME, data=[row])
            return
        escaped = record.note_id.replace("'", "''")
        table.delete(f"note_id = '{escaped}'")
        table.add([row])
        self.ensure_ann_index()

    def _search_vector(self, vector: list[float], *, limit: int, exclude_note_id: str | None) -> list[RelatedCandidate]:
        table = self._open_table()
        if table is None:
            return []
        rows = table.search(vector).limit(limit + (1 if exclude_note_id else 0)).to_list()
        candidates: list[RelatedCandidate] = []
        for row in rows:
            note_id = str(row.get("note_id") or "")
            if not note_id or note_id == exclude_note_id:
                continue
            candidates.append(_candidate_from_row(row))
            if len(candidates) >= limit:
                break
        return candidates

    def _connect(self):
        self.lancedb_path.mkdir(parents=True, exist_ok=True)
        import lancedb

        return lancedb.connect(str(self.lancedb_path))

    def _open_table(self, db=None):
        db = db or self._connect()
        try:
            names = db.table_names()
        except Exception:
            return None
        if TABLE_NAME not in names:
            return None
        return db.open_table(TABLE_NAME)


def canonical_index_text(record: NoteRecord) -> str:
    structured = _json_object(record.structured_summary_json)
    parts = [
        f"Title: {record.title}",
        f"Quick summary: {structured.get('quick_summary') or record.summary}",
        f"Detailed summary: {structured.get('detailed_summary') or ''}",
        f"Tags: {', '.join(tags_for_record(record))}",
        f"Source kind: {record.source_kind}",
        f"Source URL: {record.source_url}",
    ]
    text = "\n".join(part for part in parts if part.strip())
    return text.strip() or f"Title: {record.title or record.note_id}"


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tags_for_record(record: NoteRecord) -> list[str]:
    data = _json_array(record.tags_json)
    return [str(item) for item in data if str(item).strip()]


def load_index_settings_from_env() -> tuple[Path, PrismDatabase, NoteIndexer]:
    sqlite_path = Path(os.getenv("SQLITE_PATH", "/data/prism.sqlite3"))
    lancedb_path = Path(os.getenv("LANCEDB_PATH", "/data/lancedb"))
    config = EmbeddingConfig(
        base_url=os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1").strip(),
        api_key=_optional_env("EMBEDDING_API_KEY"),
        model=_optional_env("EMBEDDING_MODEL"),
    )
    return sqlite_path, PrismDatabase(sqlite_path), NoteIndexer(lancedb_path, config)


def rebuild_index() -> tuple[int, int, int]:
    _, database, indexer = load_index_settings_from_env()
    indexed = skipped = failed = 0
    for record in database.list_notes_for_reindexing():
        result = indexer.index_record(record, database)
        if result.status == "indexed":
            indexed += 1
        elif result.status == "skipped":
            skipped += 1
        else:
            failed += 1
    indexer.ensure_ann_index()
    return indexed, skipped, failed


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else os.sys.argv[1:]
    if args != ["rebuild"]:
        print("Usage: PYTHONPATH=src python -m prism.index rebuild")
        raise SystemExit(2)
    indexed, skipped, failed = rebuild_index()
    print(f"indexed={indexed} skipped={skipped} failed={failed}")


def _candidate_from_row(row: dict[str, Any]) -> RelatedCandidate:
    distance = row.get("_distance")
    raw_score = row.get("_score")
    if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
        score = float(raw_score)
    elif isinstance(distance, (int, float)) and not isinstance(distance, bool):
        score = 1.0 / (1.0 + max(float(distance), 0.0))
    else:
        score = 0.0
    return RelatedCandidate(
        note_id=str(row.get("note_id") or ""),
        title=str(row.get("title") or "Untitled"),
        summary=str(row.get("summary") or ""),
        note_path=str(row.get("note_path") or ""),
        source_url=str(row.get("source_url") or ""),
        tags=_json_array(str(row.get("tags_json") or "[]")),
        score=score,
    )


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_array(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


if __name__ == "__main__":
    main()

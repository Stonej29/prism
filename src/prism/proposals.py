"""Human-in-the-loop review of graph-maintenance proposals.

The traversal job (worker/traversal.py) writes *proposals* — suggested
destructive actions (merge near-duplicates, retag, prune) — instead of applying
them. A human approves or rejects each one here; only on approval is the action
executed. Notes are the source of truth, so nothing destructive happens
automatically.

Shared by both review surfaces (Telegram bot and the web API).
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from prism.db import PrismDatabase, ProposalRecord
from prism.notes import NoteService

KIND_MERGE = "merge"
KIND_RETAG = "retag"
KIND_PRUNE = "prune"
KIND_REPURPOSE = "repurpose"


@dataclass(frozen=True)
class ProposalActionResult:
    ok: bool
    message: str
    record: ProposalRecord | None = None


def new_proposal_id(database: PrismDatabase) -> str:
    while True:
        proposal_id = secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:6].lower()
        if len(proposal_id) == 6 and not database.proposal_id_exists(proposal_id):
            return proposal_id


def proposal_note_ids(record: ProposalRecord) -> list[str]:
    return _json_list(record.note_ids_json)


def proposal_payload(record: ProposalRecord) -> dict:
    if not record.payload_json:
        return {}
    try:
        data = json.loads(record.payload_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class ProposalService:
    def __init__(self, database: PrismDatabase, notes: NoteService) -> None:
        self.database = database
        self.notes = notes

    def list_pending(self, limit: int = 50, offset: int = 0) -> list[ProposalRecord]:
        return self.database.list_proposals("pending", limit, offset)

    def count_pending(self) -> int:
        return self.database.count_proposals("pending")

    def approve(self, proposal_id: str) -> ProposalActionResult:
        record = self.database.find_by_proposal_id(proposal_id.strip().lower())
        if not record:
            return ProposalActionResult(ok=False, message=f"No proposal found for {proposal_id}.")
        if record.status != "pending":
            return ProposalActionResult(ok=False, message=f"Proposal {record.proposal_id} is already {record.status}.", record=record)

        applied_message = self._apply(record)
        resolved_at = _now()
        self.database.update_proposal_status(record.proposal_id, "approved", resolved_at)
        updated = self.database.find_by_proposal_id(record.proposal_id)
        return ProposalActionResult(ok=True, message=applied_message, record=updated)

    def reject(self, proposal_id: str) -> ProposalActionResult:
        record = self.database.find_by_proposal_id(proposal_id.strip().lower())
        if not record:
            return ProposalActionResult(ok=False, message=f"No proposal found for {proposal_id}.")
        if record.status != "pending":
            return ProposalActionResult(ok=False, message=f"Proposal {record.proposal_id} is already {record.status}.", record=record)
        if record.kind == KIND_REPURPOSE:
            # "Current is right" — pin it as a user decision so the sweep stops re-proposing.
            note_id = str(proposal_payload(record).get("note_id") or "").strip().lower()
            note = self.database.find_by_note_id(note_id)
            if note:
                self.notes.pin_purpose(note)
        self.database.update_proposal_status(record.proposal_id, "rejected", _now())
        updated = self.database.find_by_proposal_id(record.proposal_id)
        return ProposalActionResult(ok=True, message=f"Rejected proposal {record.proposal_id}.", record=updated)

    def _apply(self, record: ProposalRecord) -> str:
        """Execute the approved action. Unknown kinds are a no-op (status still recorded)."""
        if record.kind == KIND_MERGE:
            payload = proposal_payload(record)
            remove_id = str(payload.get("remove") or "").strip().lower()
            keep_id = str(payload.get("keep") or "").strip().lower()
            if not remove_id or not keep_id:
                return f"Approved {record.proposal_id} (merge): payload missing keep/remove."
            result = self.notes.merge_notes(keep_id, remove_id)
            return result.message
        if record.kind == KIND_REPURPOSE:
            payload = proposal_payload(record)
            note_id = str(payload.get("note_id") or "").strip().lower()
            proposed = payload.get("proposed")
            note = self.database.find_by_note_id(note_id)
            if not note:
                return f"Approved {record.proposal_id} (repurpose): note not found."
            try:
                updated = self.notes.set_purpose(note, proposed)  # pins as a user choice
            except ValueError as exc:
                return f"Approved {record.proposal_id} (repurpose) but purpose invalid: {exc}"
            return f"Re-classified “{note.title}” → {updated.purpose or 'Unsorted'}."
        return f"Approved {record.proposal_id} ({record.kind})."


def describe_proposal(record: ProposalRecord) -> str:
    """One-line human summary used by both review surfaces."""
    payload = proposal_payload(record)
    if record.kind == KIND_MERGE:
        sim = payload.get("similarity")
        sim_str = f" (similarity {sim:.2f})" if isinstance(sim, (int, float)) else ""
        keep = payload.get("keep_title") or payload.get("keep")
        remove = payload.get("remove_title") or payload.get("remove")
        return f"Merge near-duplicates{sim_str}: keep “{keep}”, remove “{remove}”."
    if record.kind == KIND_REPURPOSE:
        current = payload.get("current") or "Unsorted"
        return f"Re-classify “{payload.get('title')}”: {current} → {payload.get('proposed')}."
    ids = ", ".join(proposal_note_ids(record))
    return f"{record.kind} proposal for {ids or 'notes'}."


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data] if isinstance(data, list) else []

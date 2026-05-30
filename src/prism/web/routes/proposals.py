from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from prism.db import PrismDatabase
from prism.proposals import ProposalService
from prism.web.deps import get_db, get_proposals
from prism.web.serializers import proposal_to_dto

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("")
def list_proposals(status: str | None = "pending", limit: int = 50, offset: int = 0, db: PrismDatabase = Depends(get_db)) -> dict:
    records = db.list_proposals(status, limit, offset)
    return {
        "items": [proposal_to_dto(r) for r in records],
        "pending": db.count_proposals("pending"),
        "limit": limit,
        "offset": offset,
    }


@router.post("/{proposal_id}/approve")
def approve_proposal(proposal_id: str, proposals: ProposalService = Depends(get_proposals)) -> dict:
    result = proposals.approve(proposal_id)
    if not result.ok and result.record is None:
        raise HTTPException(status_code=404, detail=result.message)
    return {"ok": result.ok, "message": result.message, "proposal": proposal_to_dto(result.record) if result.record else None}


@router.post("/{proposal_id}/reject")
def reject_proposal(proposal_id: str, proposals: ProposalService = Depends(get_proposals)) -> dict:
    result = proposals.reject(proposal_id)
    if not result.ok and result.record is None:
        raise HTTPException(status_code=404, detail=result.message)
    return {"ok": result.ok, "message": result.message, "proposal": proposal_to_dto(result.record) if result.record else None}

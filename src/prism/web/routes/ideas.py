from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from prism.db import PrismDatabase
from prism.ideas import IdeaService
from prism.web.deps import get_db, get_ideas
from prism.web.schemas import GenerateIdeaBody, RateIdeaBody
from prism.web.serializers import idea_to_dto

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.get("")
def list_ideas(limit: int = 50, offset: int = 0, db: PrismDatabase = Depends(get_db)) -> dict:
    records = db.list_recent_ideas(limit, offset)
    return {"items": [idea_to_dto(r) for r in records], "limit": limit, "offset": offset}


@router.get("/{idea_id}")
def get_idea(idea_id: str, db: PrismDatabase = Depends(get_db)) -> dict:
    record = db.find_by_idea_id(idea_id.strip().lower())
    if not record:
        raise HTTPException(status_code=404, detail=f"No idea found for {idea_id}")
    return idea_to_dto(record)


@router.post("")
def generate_idea(body: GenerateIdeaBody, ideas: IdeaService = Depends(get_ideas)) -> dict:
    result = ideas.generate_idea(body.topic, prefer_favorite=body.prefer_favorite)
    return {
        "ok": result.ok,
        "message": result.message,
        "idea": idea_to_dto(result.record) if result.record else None,
    }


@router.post("/{idea_id}/rating")
def rate_idea(idea_id: str, body: RateIdeaBody, ideas: IdeaService = Depends(get_ideas)) -> dict:
    updated = ideas.record_rating(idea_id.strip().lower(), body.rating)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No idea found for {idea_id}")
    return idea_to_dto(updated)


@router.delete("/{idea_id}")
def delete_idea(idea_id: str, ideas: IdeaService = Depends(get_ideas)) -> dict:
    record = ideas.delete_idea(idea_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No idea found for {idea_id}")
    return {"ok": True, "title": record.title}

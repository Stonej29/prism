from __future__ import annotations

from fastapi import APIRouter, Depends

from prism.ideas import IdeaService
from prism.web.deps import get_ideas
from prism.web.schemas import ProfileBody

router = APIRouter(tags=["profile"])


@router.get("/profile")
def get_profile(ideas: IdeaService = Depends(get_ideas)) -> dict:
    return {"content": ideas.read_profile()}


@router.put("/profile")
def update_profile(body: ProfileBody, ideas: IdeaService = Depends(get_ideas)) -> dict:
    ideas.write_profile(body.content)
    return {"ok": True, "content": ideas.read_profile()}

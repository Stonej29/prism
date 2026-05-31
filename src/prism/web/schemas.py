"""Pydantic request bodies for mutating / slow endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SaveUrlBody(BaseModel):
    url: str = Field(..., min_length=1)
    input_source: str = Field(default="web_ui", min_length=1)


class AskBody(BaseModel):
    question: str = Field(..., min_length=1)
    limit: int = Field(default=6, ge=1, le=20)


class GenerateIdeaBody(BaseModel):
    topic: str | None = None


class RateIdeaBody(BaseModel):
    rating: int = Field(..., ge=1, le=5)


class EditTagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list)


class RenameBody(BaseModel):
    title: str = Field(..., min_length=1)


class SetStatusBody(BaseModel):
    status: str = Field(..., min_length=1)

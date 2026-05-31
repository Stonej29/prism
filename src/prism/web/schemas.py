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
    prefer_job: bool = False


class RateIdeaBody(BaseModel):
    rating: int = Field(..., ge=1, le=5)


class EditTagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list)


class RenameBody(BaseModel):
    title: str = Field(..., min_length=1)


class SetStatusBody(BaseModel):
    status: str = Field(..., min_length=1)


class BulkStatusBody(BaseModel):
    ids: list[str] = Field(..., min_length=1)
    status: str = Field(..., min_length=1)


class TraversalSettingsBody(BaseModel):
    link_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    max_links_per_note: int | None = Field(default=None, ge=1, le=50)
    max_auto_links: int | None = Field(default=None, ge=0, le=50)
    dup_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class JobFlagBody(BaseModel):
    value: bool

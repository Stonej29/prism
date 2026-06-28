"""Pydantic request bodies for mutating / slow endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SaveUrlBody(BaseModel):
    url: str = Field(..., min_length=1)
    input_source: str = Field(default="web_ui", min_length=1)
    # Skip the duplicate checks and save a fresh note anyway ("save anyway" override).
    force: bool = False


class AskBody(BaseModel):
    question: str = Field(..., min_length=1)
    limit: int = Field(default=6, ge=1, le=20)


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)


class GenerateIdeaBody(BaseModel):
    topic: str | None = None
    prefer_favorite: bool = False
    # Project Mode: scope the idea's source knowledge to a purpose, an explicit note set,
    # or selected tags (instead of the whole vault).
    purpose: str | None = None
    note_ids: list[str] | None = None
    tags: list[str] | None = None


class RateIdeaBody(BaseModel):
    rating: int = Field(..., ge=1, le=5)


class EditTagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list)


class RenameBody(BaseModel):
    title: str = Field(..., min_length=1)


class SetStatusBody(BaseModel):
    status: str = Field(..., min_length=1)


class SetPurposeBody(BaseModel):
    # None / "" / "none" / "unsorted" clears the purpose; any other value must be a
    # recognized purpose (validated server-side against PURPOSE_VALUES).
    purpose: str | None = None


class PurposeBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    description: str = Field(default="", max_length=400)


class PurposeUpdateBody(BaseModel):
    description: str = Field(default="", max_length=400)


class BulkStatusBody(BaseModel):
    ids: list[str] = Field(..., min_length=1)
    status: str = Field(..., min_length=1)


class TraversalSettingsBody(BaseModel):
    link_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    max_links_per_note: int | None = Field(default=None, ge=1, le=50)
    max_auto_links: int | None = Field(default=None, ge=0, le=50)
    dup_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class FavoriteBody(BaseModel):
    value: bool


class MergeTagBody(BaseModel):
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)


class ProfileBody(BaseModel):
    content: str = Field(..., max_length=100_000)


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=1, max_length=1024)


class SetupBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=8, max_length=1024)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=8, max_length=1024)


class SettingsBody(BaseModel):
    """Partial update of UI-editable config.

    Any field omitted/``null`` is left unchanged; an empty string clears the
    stored value (falling back to env/default); a non-empty string sets it.
    """
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_user_ids: str | None = None

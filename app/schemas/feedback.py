import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.config import settings
from app.models import FeedbackStatus
from app.schemas.common import clean_text

_MAX_META_KEYS = 20


class FeedbackIn(BaseModel):
    """Public submission payload. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=5000)
    rating: int | None = Field(default=None, ge=1, le=5)
    name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    page_url: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    # Honeypot: hidden field real users never fill in.
    website: str | None = Field(default=None, max_length=500)
    # Proof for the site's challenge, when it requires one. Opaque: the verifier interprets it.
    challenge: str | None = Field(default=None, max_length=1024)

    @field_validator("message")
    @classmethod
    def _message(cls, v: str) -> str:
        v = clean_text(v)
        if not v:
            raise ValueError("message must not be blank")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return clean_text(v)

    @field_validator("page_url")
    @classmethod
    def _page_url(cls, v: str | None) -> str | None:
        v = clean_text(v)
        if v and not re.match(r"^https?://", v, re.IGNORECASE):
            raise ValueError("page_url must be http(s)")
        return v

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, v: dict) -> dict:
        if len(v) > _MAX_META_KEYS:
            raise ValueError(f"metadata may have at most {_MAX_META_KEYS} keys")
        out = {}
        for key, val in v.items():
            if len(key) > 64:
                raise ValueError("metadata keys must be <= 64 chars")
            out[key.replace("\x00", "")] = val.replace("\x00", "")[:256] if isinstance(val, str) else val
        return out


class FeedbackReceipt(BaseModel):
    id: uuid.UUID


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message: str
    rating: int | None
    name: str | None
    email: str | None
    page_url: str | None
    metadata: dict = Field(validation_alias="meta")
    status: FeedbackStatus
    user_agent: str | None
    created_at: datetime
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    tags: list[str]
    note_count: int
    reply_count: int


class FeedbackPage(BaseModel):
    items: list[FeedbackOut]
    total: int
    total_capped: bool = False  # true: there are more than `total` matches


MAX_TAGS = 10
TAG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"


def clean_tag(value: str) -> str:
    """Tags are lower-case slugs, so "Needs Review" and "needs-review" are the same tag."""
    tag = re.sub(r"\s+", "-", value.strip().lower())
    if not re.match(TAG_PATTERN, tag):
        raise ValueError("tags are 1-32 letters, digits, '-' or '_'")
    return tag


class FeedbackUpdate(BaseModel):
    """Only the fields that are sent change; `assignee_id: null` unassigns."""

    model_config = ConfigDict(extra="forbid")

    status: FeedbackStatus | None = None
    assignee_id: uuid.UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else sorted({clean_tag(t) for t in v})

    @model_validator(mode="after")
    def _check(self) -> "FeedbackUpdate":
        if not self.model_fields_set:
            raise ValueError("nothing to update")
        if self.status is None and "status" in self.model_fields_set:
            raise ValueError("status must not be null")
        if self.tags is None and "tags" in self.model_fields_set:
            raise ValueError("tags must not be null")
        return self


class FeedbackBulk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1)
    action: Literal["set_status", "delete", "assign", "add_tag", "remove_tag"]
    status: FeedbackStatus | None = None
    assignee_id: uuid.UUID | None = None  # for assign; null unassigns
    tag: str | None = None

    @field_validator("tag")
    @classmethod
    def _tag(cls, v: str | None) -> str | None:
        return None if v is None else clean_tag(v)

    @model_validator(mode="after")
    def _check(self) -> "FeedbackBulk":
        if len(self.ids) > settings.bulk_max_ids:
            raise ValueError(f"at most {settings.bulk_max_ids} items per request")
        # Each action takes only its own argument (assign without one unassigns).
        arg = {"set_status": "status", "add_tag": "tag", "remove_tag": "tag", "assign": "assignee_id"}.get(
            self.action
        )
        given = {f for f in ("status", "tag", "assignee_id") if getattr(self, f) is not None}
        if given - {arg} or (arg in ("status", "tag") and arg not in given):
            raise ValueError(f"{self.action} takes " + (arg if arg else "no extra field"))
        return self


class BulkResult(BaseModel):
    affected: int
    skipped: int


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = clean_text(v)
        if not v:
            raise ValueError("note must not be blank")
        return v


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_id: uuid.UUID | None
    author_name: str | None = None
    body: str
    created_at: datetime


class ReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = clean_text(v)
        if not v:
            raise ValueError("reply must not be blank")
        return v


class ReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_id: uuid.UUID | None
    author_name: str | None = None
    direction: str
    source: str
    body: str
    status: str
    error: str | None
    retryable: bool
    created_at: datetime


class ReplyThread(BaseModel):
    """`available` is false when no mail provider is configured, so the UI can say why it cannot send."""

    available: bool
    items: list[ReplyOut]


class TagCount(BaseModel):
    tag: str
    count: int


class QuickCounts(BaseModel):
    mine: int
    unassigned: int


class Assignee(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str

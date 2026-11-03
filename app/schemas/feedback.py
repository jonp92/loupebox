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
            out[key.replace("\x00", "")] = (
                val.replace("\x00", "")[:256] if isinstance(val, str) else val
            )
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


class FeedbackPage(BaseModel):
    items: list[FeedbackOut]
    total: int


class FeedbackUpdate(BaseModel):
    status: FeedbackStatus


class FeedbackBulk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1)
    action: Literal["set_status", "delete"]
    status: FeedbackStatus | None = None

    @model_validator(mode="after")
    def _check(self) -> "FeedbackBulk":
        if len(self.ids) > settings.bulk_max_ids:
            raise ValueError(f"at most {settings.bulk_max_ids} items per request")
        if self.action == "set_status" and self.status is None:
            raise ValueError("status is required for set_status")
        if self.action == "delete" and self.status is not None:
            raise ValueError("status is only for set_status")
        return self


class BulkResult(BaseModel):
    affected: int
    skipped: int

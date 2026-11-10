import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import Role
from app.schemas.common import normalize_origin
from app.schemas.custom_fields import CustomField, CustomFields


class _OriginsMixin(BaseModel):
    @field_validator("allowed_origins", check_fields=False)
    @classmethod
    def _normalize(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("At most 20 origins")
        return sorted({normalize_origin(o) for o in v})


class SiteCreate(_OriginsMixin):
    name: str = Field(min_length=1, max_length=120)
    allowed_origins: list[str] = []
    daily_limit: int | None = Field(default=None, ge=1, le=1_000_000)


class SiteUpdate(_OriginsMixin):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    allowed_origins: list[str] | None = None
    is_active: bool | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    # "off" or a registered verifier key. Config is validated against that verifier's model.
    challenge_mode: str | None = Field(default=None, max_length=24)
    challenge_config: dict[str, Any] | None = None
    attachments_enabled: bool | None = None  # accept images with feedback
    custom_fields: list[CustomField] | None = None  # the whole list, replacing the old one
    # Days to keep submissions / their email address. Explicit null turns the rule off.
    retention_delete_days: int | None = Field(default=None, ge=1, le=36_500)
    retention_strip_email_days: int | None = Field(default=None, ge=1, le=36_500)

    @field_validator("custom_fields")
    @classmethod
    def _custom_fields(cls, v: list[CustomField] | None) -> list[CustomField] | None:
        if v is not None:
            CustomFields(fields=v)  # the limits that span fields: unique ids, languages, list badges
        return v


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    public_key: str
    allowed_origins: list[str]
    is_active: bool
    daily_limit: int
    challenge_mode: str
    challenge_config: dict[str, Any]
    attachments_enabled: bool
    custom_fields: list[CustomField]
    retention_delete_days: int | None
    retention_strip_email_days: int | None
    created_at: datetime
    my_role: Role | None = None
    # Server-wide limits, read-only: shown next to the "accept images" switch.
    attachment_max_count: int = 0
    attachment_max_bytes: int = 0
    attachments_ready: bool = True  # false while the image storage is not fully set up


class VerifierOut(BaseModel):
    key: str
    label: str
    config_schema: dict[str, Any]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None
    role: Role


class MemberUpsert(BaseModel):
    email: EmailStr
    role: Role


class UserSuggestion(BaseModel):
    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None

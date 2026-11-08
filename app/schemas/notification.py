import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import OutboxStatus, Role
from app.notifications.events import EVENT_TYPES
from app.notifications.filters import ChannelFilters

MAX_EXTRA_RECIPIENTS = 20


class _ChannelFields(BaseModel):
    @field_validator("events", check_fields=False)
    @classmethod
    def _known_events(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        unknown = sorted(set(v) - EVENT_TYPES.keys())
        if unknown:
            raise ValueError(f"Unknown event: {', '.join(unknown)}")
        return sorted(set(v))

    @field_validator("extra_recipients", check_fields=False)
    @classmethod
    def _recipients(cls, v: list[EmailStr] | None) -> list[str] | None:
        if v is None:
            return v
        unique = list(dict.fromkeys(a.lower() for a in v))
        if len(unique) > MAX_EXTRA_RECIPIENTS:
            raise ValueError(f"At most {MAX_EXTRA_RECIPIENTS} extra recipients")
        return unique


class ChannelCreate(_ChannelFields):
    provider: str = Field(max_length=32)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    config: dict = {}
    events: list[str] = ["feedback.created"]
    min_role: Role = Role.admin
    filters: ChannelFilters = ChannelFilters()
    extra_recipients: list[EmailStr] = []


class ChannelUpdate(_ChannelFields):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    config: dict | None = None
    events: list[str] | None = None
    min_role: Role | None = None
    filters: ChannelFilters | None = None
    extra_recipients: list[EmailStr] | None = None


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    name: str
    enabled: bool
    config: dict
    events: list[str]
    min_role: Role
    filters: ChannelFilters
    extra_recipients: list[str]
    has_secret: bool  # the secret itself is only returned once, when it is created or rotated
    created_at: datetime
    updated_at: datetime


class ChannelCreated(ChannelOut):
    secret: str | None = None


class SecretOut(BaseModel):
    secret: str


class ProviderOut(BaseModel):
    key: str
    label: str
    configured: bool  # server-side settings (API key, sender) are present
    uses_recipients: bool  # sent to people (role + extra addresses) rather than to one endpoint
    signs: bool  # channels get a signing secret
    config_schema: dict  # JSON Schema of the provider's per-channel settings


class DeliveryOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID | None
    channel_name: str | None
    event_type: str
    status: OutboxStatus
    attempts: int
    summary: bool  # covered by a rolled-up summary email
    last_error: str | None
    created_at: datetime
    next_attempt_at: datetime
    sent_at: datetime | None


class TestResult(BaseModel):
    __test__ = False  # not a pytest class

    status: Literal["sent", "retry", "failed"]
    error: str | None = None
    to: str | None = None  # the address a test email went to; none for endpoint-style providers

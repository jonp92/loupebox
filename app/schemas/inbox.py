import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.models import FeedbackStatus, Role
from app.schemas.dashboard import DashboardItem


class InboxItem(DashboardItem):
    my_role: Role  # the caller's role on the item's site, so the list knows what it may offer


class InboxPage(BaseModel):
    items: list[InboxItem]
    total: int
    total_capped: bool = False


class InboxCounts(BaseModel):
    mine: int
    mine_capped: bool = False
    unassigned: int
    unassigned_capped: bool = False
    unread: int
    unread_capped: bool = False


class InboxBulk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1)
    action: Literal["set_status", "assign_me", "unassign"]
    status: FeedbackStatus | None = None

    @model_validator(mode="after")
    def _check(self) -> "InboxBulk":
        if len(self.ids) > settings.bulk_max_ids:
            raise ValueError(f"at most {settings.bulk_max_ids} items per request")
        if (self.action == "set_status") != (self.status is not None):
            raise ValueError("only set_status takes a status, and it needs one")
        return self

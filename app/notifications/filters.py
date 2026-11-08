"""Per-channel filters: which feedback items a channel hears about.

Evaluated when an event is queued (outbox._enqueue), so an item a channel doesn't want never gets an outbox
row. All the fields the filter sets must match (AND); the issue types are alternatives (OR). An empty filter
matches everything. Only what is known when an item arrives can be filtered: tags and assignee are not.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.models import Feedback
from app.notifications.events import ISSUE_TYPE, issue_type_of

log = logging.getLogger("loupebox.notifications")

NO_TYPE = "(none)"  # items without an issue type; can't collide with a real type (see ISSUE_TYPE)


class ChannelFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_types: list[str] = Field(default_factory=list, max_length=20)
    rating_min: int | None = Field(default=None, ge=1, le=5)
    rating_max: int | None = Field(default=None, ge=1, le=5)
    has_email: bool | None = None
    page_contains: str = Field(default="", max_length=200)

    @field_validator("issue_types")
    @classmethod
    def _types(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t != NO_TYPE and not ISSUE_TYPE.match(t)]
        if bad:
            raise ValueError(f"Not an issue type: {', '.join(bad)}")
        return sorted(set(v))

    @field_validator("page_contains")
    @classmethod
    def _page(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _range(self) -> "ChannelFilters":
        if self.rating_min and self.rating_max and self.rating_min > self.rating_max:
            raise ValueError("The lowest rating is above the highest")
        return self


def matches(filters: dict | None, item: Feedback) -> bool:
    """Whether a channel with these stored filters wants `item`."""
    try:
        f = ChannelFilters.model_validate(filters or {})
    except ValidationError:  # unreadable filters must not silently drop notifications
        log.warning("ignoring unreadable channel filters")
        return True
    if f.issue_types and (issue_type_of(item) or NO_TYPE) not in f.issue_types:
        return False
    if f.rating_min or f.rating_max:
        if item.rating is None:
            return False
        if item.rating < (f.rating_min or 1) or item.rating > (f.rating_max or 5):
            return False
    if f.has_email is not None and bool(item.email) != f.has_email:
        return False
    return not f.page_contains or f.page_contains.lower() in (item.page_url or "").lower()

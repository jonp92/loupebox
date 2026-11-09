import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel

from app.models import Feedback
from app.schemas.feedback import FeedbackOut
from app.schemas.site import SiteOut


class DashboardSite(SiteOut):
    new_count: int
    series: list[int]  # non-spam received per day over the window, oldest first, last = today (UTC)


class DashboardItem(FeedbackOut):
    site_id: uuid.UUID
    site_name: str

    @classmethod
    def of(cls, f: Feedback, site_name: str, **extra) -> Self:
        """An item of any site's feedback, labelled with its site."""
        fields = FeedbackOut.model_validate(f).model_dump()
        fields["meta"] = fields.pop("metadata")  # FeedbackOut validates `metadata` from the ORM's `meta`
        return cls(**fields, site_id=f.site_id, site_name=site_name, **extra)


class Dashboard(BaseModel):
    days: int
    received: int  # non-spam, last `days` days including today
    received_previous: int  # the `days` days before that
    received_today: int
    spam: int  # quarantined in the window
    oldest_unread_at: datetime | None
    series: list[int]
    new_total: int
    sites_with_new: int
    sites: list[DashboardSite]
    recent_new: list[DashboardItem]
    assigned_total: int
    assigned: list[DashboardItem]

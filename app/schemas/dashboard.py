import uuid

from pydantic import BaseModel

from app.schemas.feedback import FeedbackOut
from app.schemas.site import SiteOut


class DashboardSite(SiteOut):
    new_count: int


class DashboardItem(FeedbackOut):
    site_id: uuid.UUID
    site_name: str


class Dashboard(BaseModel):
    new_total: int
    new_24h: int
    sites_with_new: int
    sites: list[DashboardSite]
    recent_new: list[DashboardItem]

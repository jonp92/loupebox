from datetime import date

from pydantic import BaseModel


class DayStats(BaseModel):
    day: date
    accepted: int  # stored feedback that isn't currently marked spam
    quarantined: int  # stored with status=spam (link-heavy, or marked spam by staff)
    honeypot: int
    duplicate: int
    origin_denied: int
    rate_limited: int
    daily_limit: int
    challenge_failed: int


class SiteStats(BaseModel):
    days: list[DayStats]  # oldest first, one entry per day, zero-filled, ending today (UTC)

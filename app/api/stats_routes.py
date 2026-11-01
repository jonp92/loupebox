from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, site_access
from app.db.session import get_db
from app.models import Feedback, FeedbackStatus, Role, SiteStat
from app.schemas.stats import DayStats, SiteStats

router = APIRouter(prefix="/sites/{site_id}/stats", tags=["stats"])


@router.get("")
def site_stats(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    days: int = Query(default=14, ge=1, le=90),
) -> SiteStats:
    today = datetime.now(UTC).date()
    first = today - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    buckets = {first + timedelta(days=i): DayStats(day=first + timedelta(days=i), accepted=0,
               quarantined=0, honeypot=0, duplicate=0, origin_denied=0, rate_limited=0,
               daily_limit=0) for i in range(days)}

    day_col = func.date(Feedback.created_at)
    rows = db.execute(
        select(
            day_col,
            func.sum(case((Feedback.status == FeedbackStatus.spam, 1), else_=0)),
            func.count(),
        )
        .where(Feedback.site_id == access.site.id, Feedback.created_at >= start)
        .group_by(day_col)
    )
    for day, spam, total in rows:
        bucket = buckets.get(day if isinstance(day, date) else date.fromisoformat(str(day)))
        if bucket:
            bucket.quarantined = int(spam or 0)
            bucket.accepted = int(total) - bucket.quarantined

    for stat in db.scalars(
        select(SiteStat).where(SiteStat.site_id == access.site.id, SiteStat.day >= first)
    ):
        bucket = buckets.get(stat.day)
        if bucket and hasattr(bucket, stat.kind):
            setattr(bucket, stat.kind, stat.count)

    return SiteStats(days=list(buckets.values()))

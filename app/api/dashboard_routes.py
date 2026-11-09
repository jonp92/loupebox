import heapq
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, visible_sites
from app.db.session import get_db
from app.models import NOT_SPAM, Feedback, FeedbackStatus, Site, User
from app.models.user import utcnow
from app.schemas.dashboard import Dashboard, DashboardItem, DashboardSite
from app.schemas.site import SiteOut


class Window(IntEnum):
    """Days the dashboard looks back; a fixed set keeps the grouped read bounded."""

    week = 7
    month = 30
    quarter = 90


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
    window: Window = Window.week,
) -> Dashboard:
    """Unread backlog, plus what arrived in the last `days` days (and the `days` before, for the change)."""
    days = int(window)
    rows = visible_sites(db, user)
    site_ids = [s.id for s, _ in rows]
    # Both reads are index range scans (site_id, status, created_at / site_id, created_at); nothing scans a
    # site's whole history. Unread: one row per site with its count and oldest item.
    unread = (
        db.execute(
            select(Feedback.site_id, func.count(), func.min(Feedback.created_at))
            .where(Feedback.site_id.in_(site_ids), Feedback.status == FeedbackStatus.new)
            .group_by(Feedback.site_id)
        ).all()
        if site_ids
        else []
    )
    per_site = {site_id: n for site_id, n, _ in unread}
    oldest_unread = min((oldest for _, _, oldest in unread), default=None)
    # Received per site and day over this window and the one before it (for the change), one grouped read.
    today = utcnow().date()
    first = today - timedelta(days=2 * days - 1)
    day_col = func.date(Feedback.created_at)
    daily = (
        db.execute(
            select(
                Feedback.site_id,
                day_col,
                func.count().filter(Feedback.status.in_(NOT_SPAM)),
                func.count().filter(Feedback.status == FeedbackStatus.spam),
            )
            .where(
                Feedback.site_id.in_(site_ids),
                Feedback.created_at >= datetime(first.year, first.month, first.day, tzinfo=UTC),
            )
            .group_by(Feedback.site_id, day_col)
        ).all()
        if site_ids
        else []
    )
    series: dict[UUID | None, list[int]] = {None: [0] * days}  # None = all sites
    previous = spam = 0
    for site_id, day, received, junk in daily:
        age = (today - (day if isinstance(day, date) else date.fromisoformat(str(day)))).days
        if age >= days:
            previous += received
            continue
        spam += junk
        for key in (None, site_id):
            series.setdefault(key, [0] * days)[days - 1 - age] += received
    # The newest unread items: the newest few of each site that has any (one index lookup each), then the
    # newest overall. A single query over all the sites would sort every unread item.
    names = {site.id: site.name for site, _ in rows}
    newest = [
        f
        for site_id in per_site
        for f in db.scalars(
            select(Feedback)
            .where(Feedback.site_id == site_id, Feedback.status == FeedbackStatus.new)
            .order_by(Feedback.created_at.desc())
            .limit(limit)
        )
    ]
    recent = [(f, names[f.site_id]) for f in heapq.nlargest(limit, newest, key=lambda f: f.created_at)]

    # Open items (not archived or spam) the caller has been assigned, on sites they can still see.
    mine = [
        Feedback.site_id.in_(site_ids),
        Feedback.assignee_id == user.id,
        Feedback.status.in_([FeedbackStatus.new, FeedbackStatus.read]),
    ]
    assigned_total = (
        (db.scalar(select(func.count()).select_from(Feedback).where(*mine)) or 0) if site_ids else 0
    )
    assigned = (
        db.execute(
            select(Feedback, Site.name)
            .join(Site, Site.id == Feedback.site_id)
            .where(*mine)
            .order_by(Feedback.created_at.desc())
            .limit(limit)
        ).all()
        if assigned_total
        else []
    )

    sites = []
    for site, role in rows:
        out = SiteOut.model_validate(site)
        out.my_role = role
        sites.append(
            DashboardSite(
                **out.model_dump(),
                new_count=per_site.get(site.id, 0),
                series=series.get(site.id, [0] * days),
            )
        )
    return Dashboard(
        days=days,
        received=sum(series[None]),
        received_previous=previous,
        received_today=series[None][-1],
        spam=spam,
        oldest_unread_at=oldest_unread,
        series=series[None],
        new_total=sum(per_site.values()),
        sites_with_new=len(per_site),
        sites=sites,
        recent_new=[DashboardItem.of(f, name) for f, name in recent],
        assigned_total=assigned_total,
        assigned=[DashboardItem.of(f, name) for f, name in assigned],
    )

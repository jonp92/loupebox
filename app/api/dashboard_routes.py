import heapq
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import NOT_SPAM, Feedback, FeedbackStatus, Membership, Role, Site, User
from app.models.user import utcnow
from app.schemas.dashboard import Dashboard, DashboardItem, DashboardSite
from app.schemas.feedback import FeedbackOut
from app.schemas.site import SiteOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _item(f: Feedback, site_name: str) -> DashboardItem:
    fields = FeedbackOut.model_validate(f).model_dump()
    fields["meta"] = fields.pop("metadata")  # FeedbackOut validates `metadata` from the ORM's `meta`
    return DashboardItem(**fields, site_id=f.site_id, site_name=site_name)


@router.get("")
def dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> Dashboard:
    """Unread (status `new`) and total non-spam feedback across every site the caller can see."""
    if user.is_superadmin:
        rows = [(s, Role.admin) for s in db.scalars(select(Site).order_by(Site.name))]
    else:
        rows = db.execute(
            select(Site, Membership.role)
            .join(Membership, Membership.site_id == Site.id)
            .where(Membership.user_id == user.id)
            .order_by(Site.name)
        ).all()
    site_ids = [s.id for s, _ in rows]
    # One pass over the caller's sites for the three counts (instead of one scan each).
    day_ago = utcnow() - timedelta(hours=24)
    counts = (
        db.execute(
            select(
                Feedback.site_id,
                func.count().filter(Feedback.status == FeedbackStatus.new),
                func.count().filter(Feedback.status.in_(NOT_SPAM)),
                func.count().filter(Feedback.status == FeedbackStatus.new, Feedback.created_at > day_ago),
            )
            .where(Feedback.site_id.in_(site_ids))
            .group_by(Feedback.site_id)
        ).all()
        if site_ids
        else []
    )
    per_site = {site_id: unread for site_id, unread, _, _ in counts if unread}
    received_total = sum(received for _, _, received, _ in counts)
    new_24h = sum(recent_24h for _, _, _, recent_24h in counts)
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
        sites.append(DashboardSite(**out.model_dump(), new_count=per_site.get(site.id, 0)))
    return Dashboard(
        new_total=sum(per_site.values()),
        new_24h=new_24h or 0,
        received_total=received_total,
        sites_with_new=len(per_site),
        sites=sites,
        recent_new=[_item(f, name) for f, name in recent],
        assigned_total=assigned_total,
        assigned=[_item(f, name) for f, name in assigned],
    )

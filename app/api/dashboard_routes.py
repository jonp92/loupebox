from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Feedback, FeedbackStatus, Membership, Role, Site, User
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
    """Unread (status `new`) feedback across every site the caller can see."""
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
    unread = [Feedback.site_id.in_(site_ids), Feedback.status == FeedbackStatus.new]

    per_site = dict(
        db.execute(select(Feedback.site_id, func.count()).where(*unread).group_by(Feedback.site_id)).all()
    ) if site_ids else {}
    new_24h = db.scalar(
        select(func.count()).select_from(Feedback).where(*unread, Feedback.created_at > utcnow() - timedelta(hours=24))
    ) if site_ids else 0
    recent = db.execute(
        select(Feedback, Site.name)
        .join(Site, Site.id == Feedback.site_id)
        .where(*unread)
        .order_by(Feedback.created_at.desc())
        .limit(limit)
    ).all() if site_ids else []

    sites = []
    for site, role in rows:
        out = SiteOut.model_validate(site)
        out.my_role = role
        sites.append(DashboardSite(**out.model_dump(), new_count=per_site.get(site.id, 0)))
    return Dashboard(
        new_total=sum(per_site.values()),
        new_24h=new_24h or 0,
        sites_with_new=len(per_site),
        sites=sites,
        recent_new=[_item(f, name) for f, name in recent],
    )

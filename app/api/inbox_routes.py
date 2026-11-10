"""The cross-site inbox: the feedback of every site the caller can see in one list. It reads and writes the
same rows as the per-site routes and applies the same rules, so the list's filters come from
`app.core.feedback_query` and a site the caller is not on never shows up (and is never named in an error)."""

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, visible_sites
from app.core.audit import audit
from app.core.cache import menus
from app.core.feedback_query import TOTAL_CAP, Filters, assignable, capped_count, conditions, filters, sort_by
from app.db.session import get_db
from app.models import ROLE_RANK, Feedback, FeedbackStatus, Role, User
from app.schemas.feedback import BulkResult
from app.schemas.inbox import InboxBulk, InboxCounts, InboxItem, InboxPage

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _scope(db: Session, user: User, site_id: uuid.UUID | None) -> tuple[dict, list]:
    """The visible sites by id, and the condition that limits a query to them (or to the one asked for).
    A superadmin sees every site, so no condition is needed."""
    sites = {site.id: (site, role) for site, role in visible_sites(db, user)}
    if site_id is not None:
        if site_id not in sites:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
        return sites, [Feedback.site_id == site_id]
    return sites, [] if user.is_superadmin else [Feedback.site_id.in_(list(sites))]


@router.get("")
def list_inbox(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    f: Filters = Depends(filters),
    order: tuple = Depends(sort_by),
    site_id: uuid.UUID | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> InboxPage:
    sites, scope = _scope(db, user, site_id)
    if not sites:
        return InboxPage(items=[], total=0)
    where = conditions(f, *scope)
    total, capped = capped_count(db, where, max(TOTAL_CAP, offset + limit))
    rows = db.scalars(
        select(Feedback).where(*where).order_by(*order).limit(limit).offset(offset)
    )
    items = [InboxItem.of(r, sites[r.site_id][0].name, my_role=sites[r.site_id][1]) for r in rows]
    return InboxPage(items=items, total=total, total_capped=capped)


@router.get("/counts")
def inbox_counts(
    user: User = Depends(get_current_user), db: Session = Depends(get_db), site_id: uuid.UUID | None = None
) -> InboxCounts:
    """Sizes of the quick tabs: what is assigned to the caller, what is nobody's, and what is unread
    (spam excluded)."""
    sites, scope = _scope(db, user, site_id)
    if not sites:
        return InboxCounts(mine=0, unassigned=0, unread=0)

    def count(*extra, f: Filters | None = None) -> tuple[int, bool]:
        return capped_count(db, conditions(f or Filters(), *scope, *extra), TOTAL_CAP)

    mine, mine_capped = count(Feedback.assignee_id == user.id)
    unassigned, unassigned_capped = count(Feedback.assignee_id.is_(None))
    unread, unread_capped = count(f=Filters(status=FeedbackStatus.new))
    return InboxCounts(
        mine=mine,
        mine_capped=mine_capped,
        unassigned=unassigned,
        unassigned_capped=unassigned_capped,
        unread=unread,
        unread_capped=unread_capped,
    )


@router.post("/bulk")
def bulk_inbox(
    body: InboxBulk, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BulkResult:
    """Change the status of, or assign to the caller, items from several sites. Each site's own rules
    apply: an item is skipped (not an error, and not revealed) unless the caller is an editor there, and
    "assign to me" also needs them to be an editor or admin member of that site."""
    sites = {site.id: (site, role) for site, role in visible_sites(db, user)}
    ids = set(body.ids)
    by_site = defaultdict(list)
    for item in db.scalars(select(Feedback).where(Feedback.id.in_(ids))):
        if item.site_id in sites and ROLE_RANK[sites[item.site_id][1]] >= ROLE_RANK[Role.editor]:
            by_site[item.site_id].append(item)
    affected = 0
    for site_id, items in by_site.items():
        site = sites[site_id][0]
        if body.action == "set_status":
            for item in items:
                item.status = body.status
        else:
            assignee = user.id if body.action == "assign_me" else None
            if assignee and db.scalar(assignable(site_id).where(User.id == assignee)) is None:
                continue
            for item in items:
                item.assignee_id = assignee
            audit(  # ids and counts only, as for the per-site bulk assign (status changes are not logged)
                db,
                user,
                "feedback.bulk_assign",
                f"Assigned {len(items)} feedback items on {site.name}",
                target_type="site",
                target_id=site.id,
                site=site,
                details={
                    "count": len(items),
                    "assignee_id": str(assignee) if assignee else None,
                    "ids": sorted(str(i.id) for i in items),
                },
            )
        affected += len(items)
    db.commit()
    for site_id in by_site:
        menus.invalidate(site_id)
    return BulkResult(affected=affected, skipped=len(ids) - affected)

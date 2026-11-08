"""The feedback list's filters and queries, shared by the per-site list and the cross-site inbox."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.models import NOT_SPAM, Feedback, FeedbackStatus, FeedbackTag, Membership, Role, User
from app.schemas.feedback import TAG_PATTERN

TOTAL_CAP = 10_000  # the list and the quick tabs stop counting here
ISSUE_TYPE = r"^[a-z0-9_-]{1,32}$"  # what the widget's badges send as metadata.issue_type
issue_type_col = Feedback.meta["issue_type"].as_string()


def capped_count(db: Session, where: list, cap: int) -> tuple[int, bool]:
    """How many rows match, counting at most `cap`; the flag says there are more. Counting every match costs
    as much as the site is big."""
    matches = select(Feedback.id).where(*where).limit(cap + 1).subquery()
    counted = db.scalar(select(func.count()).select_from(matches))
    return min(counted, cap), counted > cap


class Filters(BaseModel):
    """The list's filters, shared by the list, the CSV export and (via the UI) bulk actions."""

    status: FeedbackStatus | None = None
    q: str | None = None
    issue_type: str | None = None
    rating: int | None = None
    has_email: bool | None = None
    created_from: date | None = None  # inclusive, UTC days
    created_to: date | None = None
    assignee: str | None = None  # a user id, or "none" for unassigned
    tag: str | None = None


def filters(
    status_filter: FeedbackStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    issue_type: str | None = Query(default=None, pattern=ISSUE_TYPE),
    rating: int | None = Query(default=None, ge=1, le=5),
    has_email: bool | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    assignee: str | None = Query(
        default=None, pattern=r"^(none|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
    ),
    tag: str | None = Query(default=None, pattern=TAG_PATTERN),
) -> Filters:
    return Filters(
        status=status_filter,
        q=q,
        issue_type=issue_type,
        rating=rating,
        has_email=has_email,
        created_from=created_from,
        created_to=created_to,
        assignee=assignee,
        tag=tag,
    )


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def conditions(f: Filters, *scope: ColumnElement) -> list:
    """The conditions for filters `f` within `scope` (the site, or the sites, being listed)."""
    conds = list(scope)
    if f.issue_type:
        conds.append(issue_type_col == f.issue_type)
    if f.status:
        conds.append(Feedback.status == f.status)
    else:
        # Spam stays out of the default view; ask for status=spam to see it.
        conds.append(Feedback.status.in_(NOT_SPAM))
    if f.rating:
        conds.append(Feedback.rating == f.rating)
    if f.has_email is not None:
        has = Feedback.email.is_not(None) & (Feedback.email != "")
        conds.append(has if f.has_email else ~has)
    if f.created_from:
        conds.append(Feedback.created_at >= _day_start(f.created_from))
    if f.created_to:
        conds.append(Feedback.created_at < _day_start(f.created_to + timedelta(days=1)))
    if f.assignee == "none":
        conds.append(Feedback.assignee_id.is_(None))
    elif f.assignee:
        conds.append(Feedback.assignee_id == uuid.UUID(f.assignee))
    if f.tag:
        conds.append(Feedback.id.in_(select(FeedbackTag.feedback_id).where(FeedbackTag.tag == f.tag)))
    if f.q:
        conds.append(
            or_(
                Feedback.message.icontains(f.q, autoescape=True),
                Feedback.email.icontains(f.q, autoescape=True),
                Feedback.name.icontains(f.q, autoescape=True),
            )
        )
    return conds


def assignable(site_id: uuid.UUID):
    """Users who can hold an assignment on the site: its active editors and admins."""
    return (
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.site_id == site_id,
            Membership.role.in_([Role.editor, Role.admin]),
            User.is_active.is_(True),
        )
    )

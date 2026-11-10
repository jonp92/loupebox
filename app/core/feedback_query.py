"""The feedback list's filters and queries, shared by the per-site list and the cross-site inbox."""

import re
import uuid
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.models import NOT_SPAM, Feedback, FeedbackStatus, FeedbackTag, Membership, Role, User
from app.schemas.custom_fields import FIELD_ID, MAX_FIELDS, TEXT_LIMIT
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
    fields: dict[str, str] = {}  # custom field id -> wanted answer; only a single site's list can use these


def _field_filters(raw: list[str]) -> dict[str, str]:
    """`cf=plan:pro` pairs as {id: value}; conditions() checks the ids against the site."""
    out: dict[str, str] = {}
    for pair in raw:
        field_id, _, value = pair.partition(":")
        if not re.fullmatch(FIELD_ID, field_id) or not 1 <= len(value) <= TEXT_LIMIT:
            raise HTTPException(422, "A field filter looks like cf=<field id>:<value>")
        out[field_id] = value
    return out


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
    cf: list[str] = Query(default=[], max_length=MAX_FIELDS),
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
        fields=_field_filters(cf),
    )


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _field_condition(field: dict, value: str) -> ColumnElement:
    """One custom-field filter. A choice matches its stored value (so an option the site has since removed can
    still be found), a checkbox is yes or no as stored, and text is a case-insensitive contains."""
    col = Feedback.meta[field["id"]]
    if field["type"] == "checkbox":
        if value not in ("true", "false"):
            raise HTTPException(422, f"{field['id']} is a checkbox: use true or false")
        return col.as_boolean() == (value == "true")
    if field["type"] == "select":
        return col.as_string() == value
    return col.as_string().icontains(value, autoescape=True)


def _field_conditions(wanted: dict[str, str], site_fields: list[dict] | None) -> list[ColumnElement]:
    defined = {d["id"]: d for d in site_fields or []}
    if unknown := sorted(set(wanted) - set(defined)):
        raise HTTPException(422, f"Unknown field {unknown[0]!r}")
    return [_field_condition(defined[field_id], value) for field_id, value in wanted.items()]


def conditions(f: Filters, *scope: ColumnElement, site_fields: list[dict] | None = None) -> list:
    """The conditions for filters `f` within `scope` (the site, or the sites, being listed). `site_fields` are
    that site's custom fields, which the field filters are checked against; without them there are none."""
    conds = [*scope, *_field_conditions(f.fields, site_fields)]
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

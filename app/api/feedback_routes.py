import csv
import io
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, site_access
from app.core.audit import audit
from app.core.config import settings
from app.db.session import get_db, get_sessionmaker
from app.models import ROLE_RANK, Feedback, FeedbackStatus, Role
from app.schemas.feedback import BulkResult, FeedbackBulk, FeedbackOut, FeedbackPage, FeedbackUpdate

router = APIRouter(prefix="/sites/{site_id}/feedback", tags=["feedback"])


def _get(db: Session, site_id: uuid.UUID, feedback_id: uuid.UUID) -> Feedback:
    item = db.scalar(
        select(Feedback).where(Feedback.id == feedback_id, Feedback.site_id == site_id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found")
    return item


_ISSUE_TYPE = r"^[a-z0-9_-]{1,32}$"  # what the widget's badges send as metadata.issue_type
_issue_type_col = Feedback.meta["issue_type"].as_string()


class Filters(BaseModel):
    """The list's filters, shared by the list, the CSV export and (via the UI) bulk actions."""

    status: FeedbackStatus | None = None
    q: str | None = None
    issue_type: str | None = None
    rating: int | None = None
    has_email: bool | None = None
    created_from: date | None = None  # inclusive, UTC days
    created_to: date | None = None


def filters(
    status_filter: FeedbackStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    issue_type: str | None = Query(default=None, pattern=_ISSUE_TYPE),
    rating: int | None = Query(default=None, ge=1, le=5),
    has_email: bool | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
) -> Filters:
    return Filters(
        status=status_filter, q=q, issue_type=issue_type, rating=rating, has_email=has_email,
        created_from=created_from, created_to=created_to,
    )


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _where(site_id: uuid.UUID, f: Filters) -> list:
    where = [Feedback.site_id == site_id]
    if f.issue_type:
        where.append(_issue_type_col == f.issue_type)
    if f.status:
        where.append(Feedback.status == f.status)
    else:
        # Spam stays out of the default view; ask for status=spam to see it.
        where.append(Feedback.status != FeedbackStatus.spam)
    if f.rating:
        where.append(Feedback.rating == f.rating)
    if f.has_email is not None:
        has = Feedback.email.is_not(None) & (Feedback.email != "")
        where.append(has if f.has_email else ~has)
    if f.created_from:
        where.append(Feedback.created_at >= _day_start(f.created_from))
    if f.created_to:
        where.append(Feedback.created_at < _day_start(f.created_to + timedelta(days=1)))
    if f.q:
        where.append(
            or_(
                Feedback.message.icontains(f.q, autoescape=True),
                Feedback.email.icontains(f.q, autoescape=True),
                Feedback.name.icontains(f.q, autoescape=True),
            )
        )
    return where


@router.get("")
def list_feedback(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    f: Filters = Depends(filters),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FeedbackPage:
    where = _where(access.site.id, f)
    total = db.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0
    rows = db.scalars(
        select(Feedback).where(*where).order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
    )
    return FeedbackPage(items=[FeedbackOut.model_validate(r) for r in rows], total=total)


CSV_COLUMNS = ("id", "created_at", "status", "issue_type", "rating", "name", "email", "message", "page_url", "meta")
# A spreadsheet treats a cell starting with one of these as a formula. Submitter text is untrusted.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> object:
    """Neutralise formula injection (OWASP "CSV injection"): text that would run as a formula is
    prefixed with an apostrophe, which spreadsheets show as plain text. Numbers pass through."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _issue_type_of(item: Feedback) -> str | None:
    value = (item.meta or {}).get("issue_type")
    return value if isinstance(value, str) and re.match(_ISSUE_TYPE, value) else None


def _csv_rows(site_id: uuid.UUID, where: list) -> Iterator[str]:
    """Stream the file in batches, on its own session: the request's session may be closed by the time
    the response body is produced."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")

    def flush() -> str:
        text = buf.getvalue()
        buf.seek(0)
        buf.truncate()
        return text

    yield "\ufeff"  # byte-order mark so Excel reads the file as UTF-8
    writer.writerow(CSV_COLUMNS)
    yield flush()
    with get_sessionmaker()() as db:
        stmt = (
            select(Feedback)
            .where(*where)
            .order_by(Feedback.created_at.desc())
            .limit(settings.export_max_rows)
            .execution_options(yield_per=500)
        )
        for n, item in enumerate(db.scalars(stmt), 1):
            created = item.created_at if item.created_at.tzinfo else item.created_at.replace(tzinfo=UTC)
            writer.writerow(
                csv_cell(v)
                for v in (
                    item.id,
                    created.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    item.status.value,
                    _issue_type_of(item),
                    item.rating,
                    item.name,
                    item.email,
                    item.message,
                    item.page_url,
                    json.dumps(item.meta, ensure_ascii=False, separators=(",", ":")) if item.meta else "",
                )
            )
            if n % 500 == 0:
                yield flush()
    yield flush()


@router.get("/issue-types")
def issue_types(
    access: SiteAccess = Depends(site_access(Role.viewer)), db: Session = Depends(get_db)
) -> list[dict]:
    """The issue types visitors have sent (from the widget's badges) with how many, for the list filter."""
    rows = db.execute(
        select(_issue_type_col, func.count())
        .where(Feedback.site_id == access.site.id, Feedback.status != FeedbackStatus.spam, _issue_type_col.is_not(None))
        .group_by(_issue_type_col)
        .order_by(func.count().desc())
    )
    return [{"id": value, "count": count} for value, count in rows if re.match(_ISSUE_TYPE, value or "")]


@router.get("/export.csv")
def export_feedback(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    f: Filters = Depends(filters),
) -> StreamingResponse:
    """The same filters as the list, as a CSV download (capped at `EXPORT_MAX_ROWS` rows)."""
    where = _where(access.site.id, f)
    total = db.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0
    audit(  # bulk personal data leaving the system; the contents are not recorded
        db, access.user, "feedback.export", f"Exported feedback from {access.site.name} as CSV",
        target_type="site", target_id=access.site.id, site=access.site,
        details={"rows": min(total, settings.export_max_rows), "status": f.status.value if f.status else None, "search": bool(f.q), "issue_type": f.issue_type,
                 "rating": f.rating, "has_email": f.has_email, "from": str(f.created_from or ""), "to": str(f.created_to or "")},
    )
    db.commit()
    slug = re.sub(r"[^a-z0-9]+", "-", access.site.name.lower()).strip("-")[:40] or "site"
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return StreamingResponse(
        _csv_rows(access.site.id, where),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="feedback-{slug}-{day}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/bulk")
def bulk_feedback(
    body: FeedbackBulk,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> BulkResult:
    """Change the status of, or delete, several items at once. Ids that are not in this site are
    skipped (not an error, and not revealed). Deleting needs the admin role, as for a single item."""
    if body.action == "delete" and ROLE_RANK[access.role] < ROLE_RANK[Role.admin]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {Role.admin.value} role")
    ids = set(body.ids)
    items = list(db.scalars(select(Feedback).where(Feedback.site_id == access.site.id, Feedback.id.in_(ids))))
    if body.action == "delete":
        audit(  # as for a single delete: ids and count only, never the messages
            db, access.user, "feedback.bulk_delete", f"Deleted {len(items)} feedback items from {access.site.name}",
            target_type="site", target_id=access.site.id, site=access.site,
            details={"count": len(items), "ids": sorted(str(i.id) for i in items)},
        )
        for item in items:
            db.delete(item)
    else:
        for item in items:
            item.status = body.status
    db.commit()
    return BulkResult(affected=len(items), skipped=len(ids) - len(items))


@router.get("/{feedback_id}")
def get_feedback(
    feedback_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    return FeedbackOut.model_validate(_get(db, access.site.id, feedback_id))


@router.patch("/{feedback_id}")
def update_feedback(
    feedback_id: uuid.UUID,
    body: FeedbackUpdate,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    item = _get(db, access.site.id, feedback_id)
    item.status = body.status
    db.commit()
    return FeedbackOut.model_validate(item)


@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(
    feedback_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> None:
    item = _get(db, access.site.id, feedback_id)
    audit(  # the message itself is personal data, so only its id and status are kept
        db, access.user, "feedback.delete", f"Deleted a feedback item from {access.site.name}",
        target_type="feedback", target_id=item.id, site=access.site, details={"status": item.status.value},
    )
    db.delete(item)
    db.commit()

import csv
import io
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, site_access
from app.core.audit import audit
from app.core.config import settings
from app.db.session import get_db, get_sessionmaker
from app.models import Feedback, FeedbackStatus, Role
from app.schemas.feedback import FeedbackOut, FeedbackPage, FeedbackUpdate

router = APIRouter(prefix="/sites/{site_id}/feedback", tags=["feedback"])


def _get(db: Session, site_id: uuid.UUID, feedback_id: uuid.UUID) -> Feedback:
    item = db.scalar(
        select(Feedback).where(Feedback.id == feedback_id, Feedback.site_id == site_id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found")
    return item


def _filters(site_id: uuid.UUID, status_filter: FeedbackStatus | None, q: str | None) -> list:
    where = [Feedback.site_id == site_id]
    if status_filter:
        where.append(Feedback.status == status_filter)
    else:
        # Spam stays out of the default view; ask for status=spam to see it.
        where.append(Feedback.status != FeedbackStatus.spam)
    if q:
        where.append(
            or_(
                Feedback.message.icontains(q, autoescape=True),
                Feedback.email.icontains(q, autoescape=True),
                Feedback.name.icontains(q, autoescape=True),
            )
        )
    return where


@router.get("")
def list_feedback(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    status_filter: FeedbackStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FeedbackPage:
    where = _filters(access.site.id, status_filter, q)
    total = db.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0
    rows = db.scalars(
        select(Feedback).where(*where).order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
    )
    return FeedbackPage(items=[FeedbackOut.model_validate(r) for r in rows], total=total)


CSV_COLUMNS = ("id", "created_at", "status", "rating", "name", "email", "message", "page_url", "meta")
# A spreadsheet treats a cell starting with one of these as a formula. Submitter text is untrusted.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> object:
    """Neutralise formula injection (OWASP "CSV injection"): text that would run as a formula is
    prefixed with an apostrophe, which spreadsheets show as plain text. Numbers pass through."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


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


@router.get("/export.csv")
def export_feedback(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    status_filter: FeedbackStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
) -> StreamingResponse:
    """The same filters as the list, as a CSV download (capped at `EXPORT_MAX_ROWS` rows)."""
    where = _filters(access.site.id, status_filter, q)
    total = db.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0
    audit(  # bulk personal data leaving the system; the contents are not recorded
        db, access.user, "feedback.export", f"Exported feedback from {access.site.name} as CSV",
        target_type="site", target_id=access.site.id, site=access.site,
        details={"rows": min(total, settings.export_max_rows), "status": status_filter.value if status_filter else None, "search": bool(q)},
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

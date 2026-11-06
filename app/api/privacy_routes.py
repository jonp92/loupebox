"""What the site holds about one email address: look it up, export it, erase it (admins).

All three take the address in a POST body so it never lands in a URL or an access log, and the audit
events record counts only.
"""

import uuid
from datetime import UTC

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, site_access
from app.core.audit import audit
from app.core.cache import menus
from app.core.config import settings
from app.core.retention import erase_email, from_email
from app.db.session import get_db
from app.models import Feedback, FeedbackNote, FeedbackReply, Role
from app.models.user import utcnow
from app.schemas.privacy import ErasureResult, PersonIn, PersonSummary

router = APIRouter(prefix="/sites/{site_id}/privacy", tags=["privacy"])


def _audit(db: Session, access: SiteAccess, action: str, summary: str, count: int) -> None:
    audit(
        db,
        access.user,
        action,
        f"{summary} for one email address on {access.site.name}",
        target_type="site",
        target_id=access.site.id,
        site=access.site,
        details={"items": count},
    )


def _by_item(db: Session, model, ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    rows: dict[uuid.UUID, list] = {}
    for row in db.scalars(select(model).where(model.feedback_id.in_(ids)).order_by(model.created_at)):
        rows.setdefault(row.feedback_id, []).append(row)
    return rows


@router.post("/lookup")
def lookup(
    body: PersonIn,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> PersonSummary:
    where = from_email(access.site.id, body.email)
    return PersonSummary(items=db.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0)


@router.post("/export")
def export_person(
    body: PersonIn,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Every item from the address with its tags, replies and internal notes, as a JSON download."""
    items = db.scalars(
        select(Feedback)
        .where(*from_email(access.site.id, body.email))
        .order_by(Feedback.created_at)
        .limit(settings.export_max_rows)
    ).all()
    ids = [i.id for i in items]
    replies, notes = _by_item(db, FeedbackReply, ids), _by_item(db, FeedbackNote, ids)
    data = {
        "site": access.site.name,
        "exported_at": utcnow().astimezone(UTC),
        "items": [
            {
                "id": i.id,
                "created_at": i.created_at,
                "status": i.status.value,
                "name": i.name,
                "email": i.email,
                "rating": i.rating,
                "message": i.message,
                "page_url": i.page_url,
                "metadata": i.meta,
                "user_agent": i.user_agent,
                "tags": i.tags,
                "replies": [
                    {"created_at": r.created_at, "direction": r.direction, "status": r.status, "body": r.body}
                    for r in replies.get(i.id, [])
                ],
                "notes": [{"created_at": n.created_at, "body": n.body} for n in notes.get(i.id, [])],
            }
            for i in items
        ],
    }
    _audit(db, access, "privacy.export", "Exported the data held", len(items))
    db.commit()
    return JSONResponse(
        jsonable_encoder(data),
        headers={
            "Content-Disposition": 'attachment; filename="person-export.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/erase")
def erase_person(
    body: PersonIn,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> ErasureResult:
    """Delete every item from the address, with its replies, notes, tags and queued notifications."""
    deleted = erase_email(db, access.site, body.email)
    _audit(db, access, "privacy.erase", "Erased the data held", deleted)
    db.commit()
    menus.invalidate(access.site.id)
    return ErasureResult(deleted=deleted)

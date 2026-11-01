import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, site_access
from app.db.session import get_db
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


@router.get("")
def list_feedback(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    status_filter: FeedbackStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FeedbackPage:
    where = [Feedback.site_id == access.site.id]
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
    total = db.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0
    rows = db.scalars(
        select(Feedback).where(*where).order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
    )
    return FeedbackPage(items=[FeedbackOut.model_validate(r) for r in rows], total=total)


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
    db.delete(_get(db, access.site.id, feedback_id))
    db.commit()

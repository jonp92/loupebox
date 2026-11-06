"""Images sent with a feedback item. They are served only here: behind a login and the site's roles,
never from a public URL, so a leaked link shows nothing."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, feedback_or_404, site_access
from app.core.attachments import delete_files
from app.core.audit import audit
from app.db.session import get_db
from app.models import FeedbackAttachment, Role
from app.schemas.feedback import AttachmentOut
from app.storage.registry import get_storage

router = APIRouter(prefix="/sites/{site_id}/feedback/{feedback_id}/attachments", tags=["attachments"])


def _attachment_or_404(
    db: Session, access: SiteAccess, feedback_id: uuid.UUID, attachment_id: uuid.UUID
) -> FeedbackAttachment:
    feedback_or_404(db, access.site.id, feedback_id)
    found = db.scalar(
        select(FeedbackAttachment).where(
            FeedbackAttachment.id == attachment_id, FeedbackAttachment.feedback_id == feedback_id
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return found


@router.get("")
def list_attachments(
    feedback_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
) -> list[AttachmentOut]:
    feedback_or_404(db, access.site.id, feedback_id)
    return list(
        db.scalars(
            select(FeedbackAttachment)
            .where(FeedbackAttachment.feedback_id == feedback_id)
            .order_by(FeedbackAttachment.created_at, FeedbackAttachment.id)
        )
    )


@router.get("/{attachment_id}")
def get_attachment(
    feedback_id: uuid.UUID,
    attachment_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
) -> Response:
    found = _attachment_or_404(db, access, feedback_id, attachment_id)
    try:
        data = get_storage().get(found.storage_key)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found") from None
    return Response(
        data,
        # The type was set by our own re-encode, never by the uploader, and nothing may sniff it into
        # something else or run as a page.
        media_type=found.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(
    feedback_id: uuid.UUID,
    attachment_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> None:
    """Remove one image and keep the message (an abusive or accidental screenshot)."""
    found = _attachment_or_404(db, access, feedback_id, attachment_id)
    key = found.storage_key
    audit(
        db,
        access.user,
        "feedback.attachment_delete",
        f"Deleted an image from a feedback item on {access.site.name}",
        target_type="feedback",
        target_id=feedback_id,
        site=access.site,
        details={"attachment_id": str(attachment_id)},
    )
    db.delete(found)
    db.commit()
    delete_files([key])

"""Replies from the team to the person who sent a feedback item, by email.

Sent synchronously through the account-mail path (no outbox), so the reply text is not queued for days and
the editor sees the outcome at once. The row records `sent` or `failed`; a temporary failure can be retried.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, feedback_or_404, site_access
from app.core.audit import audit
from app.core.config import settings
from app.core.events import publish
from app.core.rate_limit import enforce
from app.db.session import get_db
from app.inbound.registry import inbound_enabled
from app.inbound.token import reply_address
from app.models import Feedback, FeedbackReply, FeedbackStatus, Role, User, user_name
from app.notifications import system_mail
from app.notifications.outbox import enqueue_reply_sent
from app.schemas.feedback import ReplyIn, ReplyOut, ReplyThread

router = APIRouter(prefix="/sites/{site_id}/feedback/{feedback_id}/replies", tags=["replies"])

ERROR_MAX = 300


def _out(reply: FeedbackReply, author_name: str | None) -> ReplyOut:
    return ReplyOut.model_validate(reply).model_copy(update={"author_name": author_name})


def _author_name(db: Session, user: User) -> str:
    return db.scalar(select(user_name()).where(User.id == user.id))


def _check_can_send(db: Session, item: Feedback, access: SiteAccess) -> None:
    if not item.email:
        raise HTTPException(status.HTTP_409_CONFLICT, "This person did not leave an email address")
    if item.status == FeedbackStatus.spam:
        raise HTTPException(status.HTTP_409_CONFLICT, "Spam cannot be replied to")
    if system_mail.mail_provider() is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No mail provider is configured on the server")
    sent = db.scalar(
        select(func.count(FeedbackReply.id)).where(
            FeedbackReply.feedback_id == item.id, FeedbackReply.status == "sent"
        )
    )
    if sent >= settings.reply_max_per_item:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"At most {settings.reply_max_per_item} replies per item"
        )
    enforce(f"reply:{access.site.id}", settings.reply_site_hourly_limit, 3600)


def _deliver(db: Session, access: SiteAccess, item: Feedback, reply: FeedbackReply) -> None:
    """Send `reply` and record the outcome on it (the caller commits)."""
    # With inbound email on, the answer comes back to the shared mailbox (and into the conversation);
    # otherwise it goes straight to the person who replied.
    inbound = reply_address(item.id) if inbound_enabled() else None
    subject, text, html = system_mail.reply_message(
        access.site.name, reply.body, item.message, None if inbound else _author_name(db, access.user)
    )
    result = system_mail.send_system_email(
        item.email, subject, text, html, "feedback.reply", reply_to=inbound or access.user.email
    )
    reply.status = "sent" if result.status == "sent" else "failed"
    reply.retryable = result.status == "retry"
    reply.error = (result.error or "")[:ERROR_MAX] or None
    reply.message_id = result.message_id
    # Ids, outcome and length only: neither the reply text nor the address goes in the log.
    audit(
        db,
        access.user,
        "feedback.reply",
        f"Replied to a feedback item on {access.site.name}",
        target_type="feedback",
        target_id=item.id,
        site=access.site,
        details={"reply_id": str(reply.id), "status": reply.status, "length": len(reply.body)},
    )
    if reply.status == "sent":
        enqueue_reply_sent(db, item, reply)


@router.get("")
def list_replies(
    feedback_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
) -> ReplyThread:
    item = feedback_or_404(db, access.site.id, feedback_id)
    rows = db.execute(
        select(FeedbackReply, user_name())
        .outerjoin(User, User.id == FeedbackReply.author_id)
        .where(FeedbackReply.feedback_id == item.id)
        .order_by(FeedbackReply.created_at)
    )
    return ReplyThread(
        available=system_mail.mail_provider() is not None,
        inbound=inbound_enabled(),
        items=[_out(r, name) for r, name in rows],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def send_reply(
    feedback_id: uuid.UUID,
    body: ReplyIn,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> ReplyOut:
    """201 even when the mail server refused it: the saved row says `failed` and why."""
    item = feedback_or_404(db, access.site.id, feedback_id)
    _check_can_send(db, item, access)
    reply = FeedbackReply(id=uuid.uuid4(), feedback_id=item.id, author_id=access.user.id, body=body.body)
    _deliver(db, access, item, reply)
    db.add(reply)
    publish(db, "thread", access.site.id, item.id)
    db.commit()
    return _out(reply, _author_name(db, access.user))


@router.post("/{reply_id}/retry")
def retry_reply(
    feedback_id: uuid.UUID,
    reply_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> ReplyOut:
    item = feedback_or_404(db, access.site.id, feedback_id)
    reply = db.scalar(
        select(FeedbackReply).where(FeedbackReply.id == reply_id, FeedbackReply.feedback_id == item.id)
    )
    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reply not found")
    if reply.status != "failed" or not reply.retryable:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a reply that failed temporarily can be retried")
    _check_can_send(db, item, access)
    reply.author_id = access.user.id  # whoever retries is the one the mail now comes from
    _deliver(db, access, item, reply)
    publish(db, "thread", access.site.id, item.id)
    db.commit()
    return _out(reply, _author_name(db, access.user))

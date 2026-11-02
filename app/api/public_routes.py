import hashlib
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import client_ip, enforce
from app.core.security import hash_ip
from app.core.stats import record
from app.db.session import get_db
from app.models import Feedback, FeedbackStatus, Site, StatKind
from app.notifications.outbox import enqueue_feedback_created
from app.schemas.feedback import FeedbackIn, FeedbackReceipt

router = APIRouter(tags=["public"])

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def ip_rate_limit(request: Request) -> str:
    """Runs before body parsing/validation and before any DB work."""
    ip = client_ip(request)
    enforce(f"pub-ip:{ip}", settings.public_ip_limit, settings.public_window_seconds)
    return ip


def resolve_site(
    request: Request,
    x_api_key: str | None = Header(default=None),
    _ip: str = Depends(ip_rate_limit),
    db: Session = Depends(get_db),
) -> Site:
    # One message for every failure so keys can't be enumerated.
    denied = HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    if not x_api_key or len(x_api_key) > 64:
        raise denied
    site = db.scalar(select(Site).where(Site.public_key == x_api_key))
    if site is None or not site.is_active:
        raise denied

    origin = request.headers.get("origin")
    if origin is None:
        # Browsers always send Origin on cross-origin POSTs; a missing one means a non-browser client.
        if settings.public_require_origin:
            record(db, site.id, StatKind.origin_denied)
            raise denied
    elif origin not in site.allowed_origins:
        record(db, site.id, StatKind.origin_denied)
        raise denied

    try:
        enforce(f"pub-key:{site.id}", settings.public_key_limit, settings.public_window_seconds)
    except HTTPException:
        record(db, site.id, StatKind.rate_limited)
        raise
    return site


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackIn,
    request: Request,
    site: Site = Depends(resolve_site),
    db: Session = Depends(get_db),
) -> FeedbackReceipt:
    # Honeypot tripped: pretend success so bots don't adapt, store nothing.
    if payload.website:
        record(db, site.id, StatKind.honeypot)
        return FeedbackReceipt(id="00000000-0000-0000-0000-000000000000")

    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.scalar(
        select(func.count())
        .select_from(Feedback)
        .where(Feedback.site_id == site.id, Feedback.created_at >= day_start)
    )
    if (today or 0) >= site.daily_limit:
        record(db, site.id, StatKind.daily_limit)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Daily limit reached")

    content_hash = hashlib.sha256(
        f"{site.id}\n{payload.message.lower()}\n{(payload.email or '').lower()}".encode()
    ).hexdigest()
    duplicate = db.scalar(
        select(Feedback.id).where(
            Feedback.site_id == site.id,
            Feedback.content_hash == content_hash,
            Feedback.created_at >= now - timedelta(minutes=settings.dedupe_window_minutes),
        )
    )
    if duplicate:
        # Idempotent: double-clicks and retries return the original receipt.
        record(db, site.id, StatKind.duplicate)
        return FeedbackReceipt(id=duplicate)

    spammy = len(_URL_RE.findall(payload.message)) > settings.spam_link_threshold
    item = Feedback(
        site_id=site.id,
        message=payload.message,
        rating=payload.rating,
        name=payload.name,
        email=payload.email.lower() if payload.email else None,
        page_url=payload.page_url,
        meta=payload.metadata,
        status=FeedbackStatus.spam if spammy else FeedbackStatus.new,
        content_hash=content_hash,
        ip_hash=hash_ip(client_ip(request)),
        user_agent=(request.headers.get("user-agent") or "")[:256] or None,
    )
    db.add(item)
    db.flush()  # assigns the id the notification payload needs
    enqueue_feedback_created(db, item)
    db.commit()
    return FeedbackReceipt(id=item.id)

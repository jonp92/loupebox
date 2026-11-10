import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile  # the parser's class; fastapi's is a subclass

from app.challenges.registry import OFF, get_verifier
from app.core.attachments import StoredFile, delete_files
from app.core.config import settings
from app.core.events import publish
from app.core.images import ImageRejected, StoredImage, process_image
from app.core.rate_limit import client_ip, enforce
from app.core.security import hash_ip
from app.core.stats import record
from app.db.session import get_db
from app.models import Feedback, FeedbackAttachment, FeedbackStatus, Site, StatKind
from app.notifications.outbox import enqueue_feedback_created
from app.schemas.feedback import FeedbackIn, FeedbackReceipt
from app.storage.registry import get_storage

router = APIRouter(tags=["public"])

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_PAYLOAD_MAX = 64 * 1024  # the JSON part of a submission with images


def ip_rate_limit(request: Request) -> str:
    """Runs before body parsing/validation and before any DB work."""
    ip = client_ip(request)
    enforce(f"pub-ip:{ip}", settings.public_ip_limit, settings.public_window_seconds)
    return ip


def _site_from_key(request: Request, x_api_key: str | None, db: Session) -> Site:
    """Look the site up by key and check Origin. Rate limits are the caller's job."""
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
    return site


def resolve_site(
    request: Request,
    x_api_key: str | None = Header(default=None),
    _ip: str = Depends(ip_rate_limit),
    db: Session = Depends(get_db),
) -> Site:
    site = _site_from_key(request, x_api_key, db)
    try:
        enforce(f"pub-key:{site.id}", settings.public_key_limit, settings.public_window_seconds)
    except HTTPException:
        record(db, site.id, StatKind.rate_limited)
        raise
    return site


def resolve_site_for_challenge(
    request: Request,
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Site:
    """Same key and Origin checks as ingest, but with its own (looser) limits so fetching a
    challenge doesn't eat the submission budget."""
    enforce(f"chal-ip:{client_ip(request)}", settings.challenge_ip_limit, settings.public_window_seconds)
    site = _site_from_key(request, x_api_key, db)
    enforce(f"chal-key:{site.id}", settings.challenge_key_limit, settings.public_window_seconds)
    return site


def _check_challenge(db: Session, site: Site, proof: str | None) -> None:
    """Enforce the site's challenge. Fails closed: a mode with no registered verifier rejects everything."""
    if site.challenge_mode == OFF:
        return
    verifier = get_verifier(site.challenge_mode)
    ok = False
    if verifier is not None and proof:
        ok = verifier.verify(db, site, verifier.ConfigModel.model_validate(site.challenge_config), proof)
    if not ok:
        record(db, site.id, StatKind.challenge_failed)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Challenge failed" if proof else "Challenge required")


@router.post("/feedback/challenge")
def get_challenge(site: Site = Depends(resolve_site_for_challenge)) -> dict[str, Any]:
    """Hand the client what it needs to prove work for the next submission. `mode` is "off" when the
    site doesn't require one, so a client can always call this first."""
    verifier = get_verifier(site.challenge_mode)
    if site.challenge_mode == OFF or verifier is None:
        return {"mode": OFF}
    return {
        "mode": site.challenge_mode,
        **verifier.issue(site, verifier.ConfigModel.model_validate(site.challenge_config)),
    }


@router.get("/feedback/config")
def get_config(site: Site = Depends(resolve_site_for_challenge)) -> dict[str, Any]:
    """What this site accepts, so the widget can offer image upload only where it will work and keep its
    metadata within the server's cap."""
    out: dict[str, Any] = {"metadata_max_keys": settings.metadata_max_keys}
    if not site.attachments_enabled or not get_storage().is_configured():
        return out | {"attachments": {"enabled": False}}
    return out | {
        "attachments": {
            "enabled": True,
            "max_count": settings.attachment_max_count,
            "max_bytes": settings.attachment_max_bytes,
            "max_edge": settings.attachment_max_edge,
        }
    }


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackIn,
    request: Request,
    site: Site = Depends(resolve_site),
    db: Session = Depends(get_db),
) -> FeedbackReceipt:
    return _accept(db, site, request, payload, [])


def _invalid(loc: tuple, message: str) -> RequestValidationError:
    """A 422 shaped like FastAPI's own, so clients read both routes the same way."""
    return RequestValidationError([{"loc": ("body", *loc), "msg": message, "type": "value_error"}])


async def read_multipart(
    request: Request, site: Site = Depends(resolve_site)
) -> tuple[FeedbackIn, list[bytes]]:
    """The body of a submission with images: a `payload` part (the usual JSON) and up to N `images` parts.
    Runs after `resolve_site`, so the key, origin and rate limits are checked before any of it is read."""
    if not site.attachments_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This site does not accept images")
    if not get_storage().is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Image storage is not set up")
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(status.HTTP_411_LENGTH_REQUIRED, "Content-Length is required")
    if int(length) > settings.attachment_request_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The upload is too large")
    form = await request.form(
        max_files=settings.attachment_max_count, max_fields=2, max_part_size=_PAYLOAD_MAX
    )
    try:
        raw = form.get("payload")
        if not isinstance(raw, str):
            raise _invalid(("payload",), "Field required")
        try:
            payload = FeedbackIn.model_validate_json(raw)
        except ValidationError as e:
            raise RequestValidationError(
                [
                    {**err, "loc": ("body", *err["loc"])}
                    for err in e.errors(include_url=False, include_context=False, include_input=False)
                ]
            ) from None
        images = [f for f in form.getlist("images") if isinstance(f, UploadFile)]
        data = [await f.read() for f in images]
    finally:
        await form.close()
    for i, blob in enumerate(data):
        if len(blob) > settings.attachment_max_bytes:
            mb = settings.attachment_max_bytes // (1024 * 1024)
            raise _invalid(("images", i), f"Each image must be under {mb} MB")
    return payload, data


@router.post("/feedback/with-images", status_code=status.HTTP_201_CREATED)
def submit_feedback_with_images(
    request: Request,
    body: tuple[FeedbackIn, list[bytes]] = Depends(read_multipart),
    site: Site = Depends(resolve_site),
    db: Session = Depends(get_db),
) -> FeedbackReceipt:
    return _accept(db, site, request, *body)


def _accept(
    db: Session, site: Site, request: Request, payload: FeedbackIn, images: list[bytes]
) -> FeedbackReceipt:
    _check_challenge(db, site, payload.challenge)

    # Honeypot tripped: pretend success so bots don't adapt, store nothing.
    if payload.website:
        record(db, site.id, StatKind.honeypot)
        return FeedbackReceipt(id="00000000-0000-0000-0000-000000000000")

    # Spam never gets its images stored. Decoding is the costly part, so it happens before the lock below.
    spammy = len(_URL_RE.findall(payload.message)) > settings.spam_link_threshold
    stored: list[StoredImage] = []
    for i, blob in enumerate([] if spammy else images):
        try:
            stored.append(process_image(blob))
        except ImageRejected as e:
            raise _invalid(("images", i), str(e)) from None

    # Concurrent submissions take turns from here to the commit, so they can't all pass the count
    # below (Postgres row lock; SQLite has a single writer anyway).
    db.execute(select(Site.id).where(Site.id == site.id).with_for_update())
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
    publish(db, "feedback", site.id, item.id)
    _store_images(db, item, stored)
    return FeedbackReceipt(id=item.id)


def _store_images(db: Session, item: Feedback, images: list[StoredImage]) -> None:
    """Write the files, then commit the item with its rows. If either fails nothing is left behind."""
    written: list[StoredFile] = []
    try:
        storage = get_storage()
        for image in images:
            attachment_id = uuid.uuid4()
            key = f"{item.site_id}/{attachment_id}"
            storage.put(key, image.data, image.content_type)
            written.append(StoredFile(storage.key, key))
            db.add(
                FeedbackAttachment(
                    id=attachment_id,
                    feedback_id=item.id,
                    site_id=item.site_id,
                    storage_key=key,
                    storage=storage.key,
                    content_type=image.content_type,
                    size=len(image.data),
                    width=image.width,
                    height=image.height,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        delete_files(written)
        raise

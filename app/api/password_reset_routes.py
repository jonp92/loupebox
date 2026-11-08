"""Self-service password reset by emailed link.

Requests always answer the same way and do their work after the response, so neither the status nor
the timing says whether an address has an account. Reset tokens are random, stored hashed, single use
and short lived. A reset changes only the password: two-factor stays on.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.accounts import new_password_hash, revoke_sessions
from app.core.audit import audit
from app.core.config import settings
from app.core.rate_limit import clear_login_failures, client_ip, enforce
from app.core.security import hash_token, new_refresh_token
from app.db.session import get_db, get_sessionmaker
from app.models import PasswordResetToken, User
from app.models.user import utcnow
from app.notifications import system_mail
from app.schemas.auth import FeaturesOut, PasswordResetConfirm, PasswordResetRequest

log = logging.getLogger("loupebox.password_reset")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/features")
def features() -> FeaturesOut:
    """What the sign-in and reset pages need. Public: whether reset links can be sent, the minimum
    password length, and whether 2FA is required."""
    return FeaturesOut(
        password_reset=system_mail.password_reset_available(),
        password_min_length=settings.password_min_length,
        require_totp=settings.require_totp,
    )


def _send_reset_email(email: str) -> None:
    """Background task: look the account up, issue a token, send it. Failures are logged, never raised."""
    try:
        with get_sessionmaker()() as db:
            user = db.scalar(select(User).where(User.email == email))
            if user is None or not user.is_active:
                return
            now = utcnow()
            # A newer request replaces older links.
            db.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
                .values(used_at=now)
            )
            token = new_refresh_token()
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(token),
                    expires_at=now + timedelta(minutes=settings.password_reset_minutes),
                )
            )
            db.commit()
            user_id = user.id
        subject, text, html = system_mail.password_reset_message(token)
        result = system_mail.send_system_email(email, subject, text, html, "password-reset")
        if result.status != "sent":
            log.warning("password reset email for user %s was not sent: %s", user_id, result.error)
    except Exception:
        log.exception("password reset email failed")


def _send_changed_email(email: str) -> None:
    try:
        subject, text, html = system_mail.password_changed_message()
        result = system_mail.send_system_email(email, subject, text, html, "password-changed")
        if result.status != "sent":
            log.warning("password-changed email was not sent: %s", result.error)
    except Exception:
        log.exception("password-changed email failed")


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_reset(
    body: PasswordResetRequest, request: Request, background: BackgroundTasks
) -> dict[str, str]:
    if not system_mail.password_reset_available():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Password reset is not available")
    email = body.email.lower()
    # Limits apply whether or not the account exists, so hitting one doesn't reveal anything.
    enforce(f"pw-reset-ip:{client_ip(request)}", settings.password_reset_ip_limit, 3600)
    enforce(f"pw-reset-email:{email}", settings.password_reset_email_limit, 3600)
    background.add_task(_send_reset_email, email)
    return {"status": "If that address has an account, a reset link is on its way."}


@router.post("/password-reset/confirm")
def confirm_reset(
    body: PasswordResetConfirm,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    enforce(f"pw-reset-confirm:{client_ip(request)}", settings.login_ip_limit, settings.login_window_seconds)
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired")
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token)))
    now = datetime.now(UTC)
    if row is None or row.used_at is not None:
        raise invalid
    user = db.get(User, row.user_id)
    if row.expires_at < now or user is None or not user.is_active:
        raise invalid

    user.password_hash = new_password_hash(body.new_password)
    db.execute(  # this link and any other outstanding ones are spent
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    revoke_sessions(db, user.id)
    audit(
        db,
        user,
        "auth.password_reset",
        "Reset their password with an emailed link",
        target_type="user",
        target_id=user.id,
        details={"password": "changed"},
    )
    db.commit()
    clear_login_failures(user.email)  # the owner proved control of the address
    background.add_task(_send_changed_email, user.email)
    return {"status": "Password changed. Sign in with your new password."}

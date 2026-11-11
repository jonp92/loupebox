"""Account changes shared by the auth, password-reset and user routes. These don't commit."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import RecoveryCode, RefreshToken, User


def revoke_sessions(db: Session, user_id: uuid.UUID) -> None:
    """Sign the user out everywhere: revoke every live refresh token, and end the grace of rotated ones."""
    now = datetime.now(UTC)
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None) | RefreshToken.rotated_at.is_not(None),
        )
        .values(revoked_at=func.coalesce(RefreshToken.revoked_at, now), rotated_at=None)
    )


def new_password_hash(password: str) -> str:
    """Hash a password someone is setting now, after the minimum length (a setting) is met."""
    if len(password) < settings.password_min_length:
        raise HTTPException(
            422,
            f"Password must be at least {settings.password_min_length} characters",
        )
    return hash_password(password)


def clear_totp(db: Session, user: User) -> None:
    """Turn off two-factor authentication and drop the recovery codes."""
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))

"""Account changes shared by the auth, password-reset and user routes. These don't commit."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models import RecoveryCode, RefreshToken, User


def revoke_sessions(db: Session, user_id: uuid.UUID) -> None:
    """Sign the user out everywhere: revoke every live refresh token."""
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def clear_totp(db: Session, user: User) -> None:
    """Turn off two-factor authentication and drop the recovery codes."""
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))

"""Turn off two-factor authentication for a user (lockout recovery): python -m scripts.reset_totp you@example.com"""
import sys
from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from app.db.session import get_sessionmaker
from app.models import RecoveryCode, RefreshToken, User


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    email = sys.argv[1].lower()
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            sys.exit(f"No such user: {email}")
        user.totp_secret = user.totp_enabled_at = user.totp_last_step = None
        db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    print(f"Two-factor authentication is off for {email}; their sessions were signed out")


if __name__ == "__main__":
    main()

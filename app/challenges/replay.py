from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import UsedChallenge


def mark_used(db: Session, challenge_id: str, expires_at: datetime) -> bool:
    """Atomically claim a challenge id. False if it was already used. Commits on success."""
    db.add(UsedChallenge(id=challenge_id, expires_at=expires_at))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def purge_expired(db: Session, now: datetime) -> int:
    """Expired challenges can't verify any more, so their replay markers can go."""
    result = db.execute(delete(UsedChallenge).where(UsedChallenge.expires_at < now))
    db.commit()
    return result.rowcount

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.avatar_routes import clear_avatar, raw_body, store_avatar
from app.api.deps import require_superadmin
from app.core.audit import audit, changed, snapshot
from app.core.security import hash_password
from app.db.session import get_db
from app.models import RefreshToken, User
from app.schemas.auth import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_superadmin)])


_USER_FIELDS = ("first_name", "last_name", "email", "is_active", "is_superadmin")


def _audit_user_update(db: Session, actor: User, user: User, before: dict, *, password_reset: bool) -> None:
    """One event per kind of change, so the log can be filtered by what happened."""
    diff = changed(before, user)
    target = {"target_type": "user", "target_id": user.id}
    who = user.email
    if "is_superadmin" in diff:
        promoted = user.is_superadmin
        audit(db, actor, "user.promote" if promoted else "user.demote",
              f"Made {who} a superadmin" if promoted else f"Removed superadmin from {who}", **target)
    if "is_active" in diff:
        audit(db, actor, "user.enable" if user.is_active else "user.disable",
              f"{'Enabled' if user.is_active else 'Disabled'} {who}", **target)
    if password_reset:
        audit(db, actor, "user.password_reset", f"Set a new password for {who}", **target, details={"password": "changed"})
    profile = {k: v for k, v in diff.items() if k not in ("is_superadmin", "is_active")}
    if profile:
        audit(db, actor, "user.update", f"Updated {who}: {', '.join(profile)}", **target, details=profile)


@router.get("")
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in db.scalars(select(User).order_by(User.email))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> UserOut:
    user = User(
        id=uuid.uuid4(),
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        is_superadmin=body.is_superadmin,
    )
    db.add(user)
    audit(
        db, actor, "user.create", f"Created user {user.email}" + (" as superadmin" if user.is_superadmin else ""),
        target_type="user", target_id=user.id, details={"email": user.email, "is_superadmin": user.is_superadmin},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return UserOut.model_validate(user)


@router.patch("/{user_id}")
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    actor: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id and (body.is_active is False or body.is_superadmin is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or disable yourself")
    before = snapshot(user, _USER_FIELDS)
    if body.first_name is not None:
        user.first_name = body.first_name.strip()
    if body.last_name is not None:
        user.last_name = body.last_name.strip()
    if body.email is not None:
        user.email = body.email.lower()
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_superadmin is not None:
        user.is_superadmin = body.is_superadmin
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    _audit_user_update(db, actor, user, before, password_reset=body.password is not None)
    if body.password is not None or body.is_active is False:
        # Force re-login everywhere.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return UserOut.model_validate(user)


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.put("/{user_id}/avatar")
def set_user_avatar(
    user_id: uuid.UUID,
    raw: bytes = Depends(raw_body),
    content_type: str | None = Header(default=None),
    actor: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get_user(db, user_id)
    audit(db, actor, "user.avatar_set", f"Changed the avatar of {user.email}", target_type="user", target_id=user.id)
    store_avatar(db, user, raw, content_type)
    return UserOut.model_validate(user)


@router.delete("/{user_id}/avatar")
def delete_user_avatar(
    user_id: uuid.UUID, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> UserOut:
    user = _get_user(db, user_id)
    audit(db, actor, "user.avatar_clear", f"Removed the avatar of {user.email}", target_type="user", target_id=user.id)
    clear_avatar(db, user)
    return UserOut.model_validate(user)

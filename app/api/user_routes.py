import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.avatar_routes import clear_avatar, raw_body, store_avatar
from app.api.deps import require_superadmin
from app.core.accounts import clear_totp, revoke_sessions
from app.core.audit import audit, changed, snapshot
from app.core.security import hash_password
from app.db.session import get_db
from app.models import User, user_matches
from app.schemas.auth import UserCreate, UserOut, UserPage, UserUpdate

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_superadmin)])


_USER_FIELDS = ("first_name", "last_name", "email", "is_active", "is_superadmin")


def _audit_user_update(db: Session, actor: User, user: User, before: dict, *, password_reset: bool) -> None:
    """One event per kind of change, so the log can be filtered by what happened."""
    diff = changed(before, user)
    target = {"target_type": "user", "target_id": user.id}
    who = user.email
    if "is_superadmin" in diff:
        promoted = user.is_superadmin
        audit(
            db,
            actor,
            "user.promote" if promoted else "user.demote",
            f"Made {who} a superadmin" if promoted else f"Removed superadmin from {who}",
            **target,
        )
    if "is_active" in diff:
        audit(
            db,
            actor,
            "user.enable" if user.is_active else "user.disable",
            f"{'Enabled' if user.is_active else 'Disabled'} {who}",
            **target,
        )
    if password_reset:
        audit(
            db,
            actor,
            "user.password_reset",
            f"Set a new password for {who}",
            **target,
            details={"password": "changed"},
        )
    profile = {k: v for k, v in diff.items() if k not in ("is_superadmin", "is_active")}
    if profile:
        audit(db, actor, "user.update", f"Updated {who}: {', '.join(profile)}", **target, details=profile)


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UserPage:
    """One page of users by email, optionally only those whose name or email contains `q`."""
    where = [user_matches(q)] if q.strip() else []
    total = db.scalar(select(func.count()).select_from(User).where(*where)) or 0
    rows = db.scalars(select(User).where(*where).order_by(User.email).limit(limit).offset(offset))
    return UserPage(items=[UserOut.model_validate(u) for u in rows], total=total)


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
        db,
        actor,
        "user.create",
        f"Created user {user.email}" + (" as superadmin" if user.is_superadmin else ""),
        target_type="user",
        target_id=user.id,
        details={"email": user.email, "is_superadmin": user.is_superadmin},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None
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
        revoke_sessions(db, user.id)  # force re-login everywhere
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None
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
    audit(
        db,
        actor,
        "user.avatar_set",
        f"Changed the avatar of {user.email}",
        target_type="user",
        target_id=user.id,
    )
    store_avatar(user, raw, content_type)
    db.commit()
    return UserOut.model_validate(user)


@router.delete("/{user_id}/avatar")
def delete_user_avatar(
    user_id: uuid.UUID, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> UserOut:
    user = _get_user(db, user_id)
    audit(
        db,
        actor,
        "user.avatar_clear",
        f"Removed the avatar of {user.email}",
        target_type="user",
        target_id=user.id,
    )
    clear_avatar(user)
    db.commit()
    return UserOut.model_validate(user)


@router.delete("/{user_id}/totp")
def reset_user_totp(
    user_id: uuid.UUID, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> UserOut:
    """Lockout recovery: turn off someone's TOTP and sign them out everywhere."""
    user = _get_user(db, user_id)
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TOTP is not enabled for this user")
    clear_totp(db, user)
    revoke_sessions(db, user.id)
    audit(
        db,
        actor,
        "user.totp_reset",
        f"Turned off two-factor authentication for {user.email}",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return UserOut.model_validate(user)

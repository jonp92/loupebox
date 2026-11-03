import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.avatar_routes import clear_avatar, raw_body, store_avatar
from app.api.deps import require_superadmin
from app.core.security import hash_password
from app.db.session import get_db
from app.models import RefreshToken, User
from app.schemas.auth import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_superadmin)])


@router.get("")
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in db.scalars(select(User).order_by(User.email))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db)) -> UserOut:
    user = User(
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        is_superadmin=body.is_superadmin,
    )
    db.add(user)
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
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get_user(db, user_id)
    store_avatar(db, user, raw, content_type)
    return UserOut.model_validate(user)


@router.delete("/{user_id}/avatar")
def delete_user_avatar(user_id: uuid.UUID, db: Session = Depends(get_db)) -> UserOut:
    user = _get_user(db, user_id)
    clear_avatar(db, user)
    return UserOut.model_validate(user)

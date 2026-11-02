from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import client_ip, enforce
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.models import RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    MembershipOut,
    MeResponse,
    PasswordChange,
    TokenResponse,
)
from app.schemas.common import sniff_image

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        _COOKIE,
        token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=settings.cookie_path,
    )


def _issue(db: Session, user: User, response: Response) -> TokenResponse:
    token = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    db.commit()
    _set_refresh_cookie(response, token)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login")
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> TokenResponse:
    ip = client_ip(request)
    email = body.email.lower()
    enforce(f"login-ip:{ip}", settings.login_ip_limit, settings.login_window_seconds)
    enforce(
        f"login-acct:{ip}:{email}", settings.login_account_limit, settings.login_window_seconds
    )

    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _issue(db, user, response)


@router.post("/refresh")
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> TokenResponse:
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if not refresh_token:
        raise invalid
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)))
    if row is None:
        raise invalid
    now = datetime.now(UTC)
    if row.revoked_at is not None:
        # A rotated token was replayed: assume theft and kill every session for this user.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise invalid
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    user = db.get(User, row.user_id)
    if expires < now or user is None or not user.is_active:
        raise invalid
    row.revoked_at = now  # rotate
    return _issue(db, user, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> None:
    if refresh_token:
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == hash_token(refresh_token),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    response.delete_cookie(_COOKIE, path=settings.cookie_path)


def _me(user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
        is_superadmin=user.is_superadmin,
        memberships=[MembershipOut(site_id=m.site_id, role=m.role) for m in user.memberships],
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return _me(user)


async def _raw_body(request: Request) -> bytes:
    return await request.body()


@router.put("/me/avatar")
def set_avatar(
    raw: bytes = Depends(_raw_body),
    content_type: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    """Upload the avatar as a raw image body. Name and email are superadmin-managed."""
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Avatar must be PNG, JPEG or WebP")
    if len(raw) > settings.avatar_max_bytes:
        raise HTTPException(
            413,
            f"Avatar must be at most {settings.avatar_max_bytes // 1024} KB",
        )
    if sniff_image(raw) != declared:
        raise HTTPException(422, "Image contents do not match its content type")
    user.avatar_data = raw
    user.avatar_type = declared
    user.avatar_updated_at = datetime.now(UTC)
    db.commit()
    return _me(user)


@router.delete("/me/avatar")
def delete_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    user.avatar_data = None
    user.avatar_type = None
    user.avatar_updated_at = None
    db.commit()
    return _me(user)


@router.post("/me/password")
def change_password(
    body: PasswordChange,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TokenResponse:
    enforce(f"pw-change:{user.id}", settings.login_account_limit, settings.login_window_seconds)
    # 400, not 401: the SPA treats 401 as "session expired".
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the current one")
    user.password_hash = hash_password(body.new_password)
    # Sign out every other session; this one continues with a fresh refresh token.
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return _issue(db, user, response)

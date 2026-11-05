from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.api.avatar_routes import clear_avatar, raw_body, store_avatar
from app.api.deps import get_current_user
from app.core import totp
from app.core.audit import audit
from app.core.config import settings
from app.core.rate_limit import (
    check_login_failures,
    clear_login_failures,
    client_ip,
    enforce,
    record_login_failure,
)
from app.core.security import (
    create_access_token,
    create_mfa_token,
    decode_mfa_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.models import RecoveryCode, RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    MembershipOut,
    MeResponse,
    MfaLogin,
    MfaRequired,
    PasswordChange,
    RecoveryCodes,
    TokenResponse,
    TotpConfirm,
    TotpEnabled,
    TotpProof,
    TotpSetup,
)

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
) -> TokenResponse | MfaRequired:
    ip = client_ip(request)
    email = body.email.lower()
    enforce(f"login-ip:{ip}", settings.login_ip_limit, settings.login_window_seconds)
    enforce(f"login-acct:{ip}:{email}", settings.login_account_limit, settings.login_window_seconds)
    check_login_failures(email)  # guesses spread over many IPs

    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        record_login_failure(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    clear_login_failures(email)
    if user.totp_enabled:
        return MfaRequired(mfa_token=create_mfa_token(user.id))
    return _issue(db, user, response)


def _enforce_mfa_limits(user: User, scope: str) -> None:
    """Separate budgets for signing in and for managing TOTP from a session, so someone who only has
    the password can't use up the budget that lets the real user change their own settings."""
    enforce(f"mfa-{scope}-min:{user.id}", settings.login_account_limit, settings.login_window_seconds)
    enforce(f"mfa-{scope}-hour:{user.id}", settings.mfa_hourly_limit, 3600)


def _recovery_codes_left(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(RecoveryCode)
            .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        )
        or 0
    )


def _check_second_factor(db: Session, user: User, code: str) -> str | None:
    """Consume `code` if it is a valid authenticator code or an unused recovery code.

    Returns "totp" or "recovery" (the caller must commit), or None. A used authenticator step is
    remembered so the same code can't be replayed.
    """
    secret = totp.decrypt_secret(user.totp_secret) if user.totp_secret else None
    if secret is None:
        return None
    step = totp.verify(secret, code, user.totp_last_step)
    if step is not None:
        user.totp_last_step = step
        return "totp"
    row = db.scalar(
        select(RecoveryCode).where(
            RecoveryCode.user_id == user.id,
            RecoveryCode.code_hash == totp.hash_recovery_code(code),
            RecoveryCode.used_at.is_(None),
        )
    )
    if row is not None:
        row.used_at = datetime.now(UTC)
        return "recovery"
    return None


def _revoke_sessions(db: Session, user: User) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


@router.post("/login/totp")
def login_totp(
    body: MfaLogin, request: Request, response: Response, db: Session = Depends(get_db)
) -> TokenResponse:
    enforce(f"login-ip:{client_ip(request)}", settings.login_ip_limit, settings.login_window_seconds)
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code")
    user_id = decode_mfa_token(body.mfa_token)
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active or not user.totp_enabled:
        raise invalid
    _enforce_mfa_limits(user, "login")
    used = _check_second_factor(db, user, body.code)
    if used is None:
        raise invalid
    if used == "recovery":
        audit(  # the account lost its authenticator or someone has a leaked code: worth a trail
            db,
            user,
            "auth.recovery_code_used",
            "Signed in with a recovery code",
            target_type="user",
            target_id=user.id,
            details={"remaining": _recovery_codes_left(db, user)},
        )
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


def _me(db: Session, user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
        is_superadmin=user.is_superadmin,
        totp_enabled=user.totp_enabled,
        recovery_codes_left=_recovery_codes_left(db, user) if user.totp_enabled else 0,
        memberships=[MembershipOut(site_id=m.site_id, role=m.role) for m in user.memberships],
    )


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    return _me(db, user)


@router.put("/me/avatar")
def set_avatar(
    raw: bytes = Depends(raw_body),
    content_type: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    """Upload the avatar as a raw image body. Name and email are superadmin-managed."""
    store_avatar(db, user, raw, content_type)
    return _me(db, user)


@router.delete("/me/avatar")
def delete_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    clear_avatar(db, user)
    return _me(db, user)


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
    _revoke_sessions(db, user)
    audit(  # self-service, but a password change is what an account takeover looks like
        db,
        user,
        "auth.password_change",
        "Changed their own password",
        target_type="user",
        target_id=user.id,
        details={"password": "changed"},
    )
    return _issue(db, user, response)


def _store_recovery_codes(db: Session, user: User) -> list[str]:
    codes = totp.new_recovery_codes()
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    db.add_all(RecoveryCode(user_id=user.id, code_hash=totp.hash_recovery_code(c)) for c in codes)
    return codes


def _require_proof(db: Session, user: User, body: TotpProof) -> str:
    """Password plus a current second factor, for changes that would weaken or reset TOTP."""
    _enforce_mfa_limits(user, "manage")
    # 400, not 401: the SPA treats 401 as "session expired".
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    used = _check_second_factor(db, user, body.code)
    if used is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    return used


@router.post("/me/totp/setup")
def totp_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TotpSetup:
    """Start (or restart) enrollment. TOTP only takes effect once `enable` confirms a code."""
    if user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TOTP is already enabled")
    secret = totp.new_secret()
    user.totp_secret = totp.encrypt_secret(secret)
    user.totp_last_step = None
    db.commit()
    return TotpSetup(secret=secret, uri=totp.provisioning_uri(user.email, secret))


@router.post("/me/totp/enable")
def totp_enable(
    body: TotpConfirm,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TotpEnabled:
    _enforce_mfa_limits(user, "manage")
    secret = totp.decrypt_secret(user.totp_secret) if user.totp_secret else None
    if user.totp_enabled or secret is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Start setup first")
    step = totp.verify(secret, body.code)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    user.totp_enabled_at = datetime.now(UTC)
    user.totp_last_step = step
    codes = _store_recovery_codes(db, user)
    _revoke_sessions(db, user)
    audit(
        db,
        user,
        "auth.totp_enable",
        "Turned on two-factor authentication",
        target_type="user",
        target_id=user.id,
    )
    token = _issue(db, user, response)
    return TotpEnabled(access_token=token.access_token, recovery_codes=codes)


@router.post("/me/totp/disable")
def totp_disable(
    body: TotpProof,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TokenResponse:
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TOTP is not enabled")
    _require_proof(db, user, body)
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    _revoke_sessions(db, user)
    audit(
        db,
        user,
        "auth.totp_disable",
        "Turned off two-factor authentication",
        target_type="user",
        target_id=user.id,
    )
    return _issue(db, user, response)


@router.post("/me/totp/recovery-codes")
def totp_new_recovery_codes(
    body: TotpProof, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RecoveryCodes:
    """Replace all recovery codes (the old ones stop working)."""
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TOTP is not enabled")
    _require_proof(db, user, body)
    codes = _store_recovery_codes(db, user)
    audit(
        db, user, "auth.recovery_codes", "Generated new recovery codes", target_type="user", target_id=user.id
    )
    db.commit()
    return RecoveryCodes(recovery_codes=codes)

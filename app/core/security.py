import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()
# Verified against when the user doesn't exist so login timing doesn't reveal accounts.
_DUMMY_HASH = _hasher.hash("not-a-real-password")

_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[_ALGORITHM], options={"require": ["exp", "sub"]}
        )
        if payload.get("type") != "access":
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_public_key() -> str:
    """Public site key. It ships in client JS, so it identifies a site rather than proving
    anything; origin checks and rate limits do the real work."""
    return "pk_" + secrets.token_urlsafe(24)


def hash_ip(ip: str) -> str:
    """Keyed hash so we can correlate abuse without storing raw IPs."""
    digest = hmac.new(settings.jwt_secret.encode(), f"ip:{ip}".encode(), hashlib.sha256)
    return digest.hexdigest()[:32]

"""Encryption at rest for secrets the server must be able to read back (TOTP seeds, webhook signing
secrets). Each purpose has its own key setting (`<PURPOSE>_ENCRYPTION_KEY`, falling back to
`JWT_SECRET`), so one can be rotated or leaked without touching the other."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet(purpose: str) -> Fernet:
    key = getattr(settings, f"{purpose}_encryption_key") or settings.jwt_secret
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"{purpose}:{key}".encode()).digest()))


def encrypt(purpose: str, value: str) -> str:
    return _fernet(purpose).encrypt(value.encode()).decode()


def decrypt(purpose: str, token: str) -> str | None:
    try:
        return _fernet(purpose).decrypt(token.encode()).decode()
    except InvalidToken:
        return None

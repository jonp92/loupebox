"""TOTP (RFC 6238, SHA-1, 6 digits, 30 s) and recovery codes, using only the standard library plus
Fernet for encrypting secrets at rest."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

STEP_SECONDS = 30
DIGITS = 6
# Accept the previous and next step too, to tolerate clock drift between phone and server.
_WINDOW = 1
RECOVERY_CODE_COUNT = 10


def _fernet() -> Fernet:
    key = settings.totp_encryption_key or settings.jwt_secret
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"totp:" + key.encode()).digest()))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()  # 160 bits, no padding needed


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify(secret: str, code: str, last_step: int | None = None, now: float | None = None) -> int | None:
    """The matching step, or None. Steps at or before `last_step` are refused so a code works once."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    step = current_step(now)
    match = None
    for s in range(step - _WINDOW, step + _WINDOW + 1):
        # No early exit: every candidate is compared so timing doesn't reveal which step matched.
        if hmac.compare_digest(_code(secret, s), code) and (last_step is None or s > last_step):
            match = s
    return match


def provisioning_uri(email: str, secret: str) -> str:
    label = quote(f"{settings.totp_issuer}:{email}")
    query = urlencode({"secret": secret, "issuer": settings.totp_issuer, "digits": DIGITS, "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"


def new_recovery_codes() -> list[str]:
    """Ten codes like `k3f9a-27xqd`: 50 bits each, from an alphabet without look-alike characters."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    def one() -> str:
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"
    return [one() for _ in range(RECOVERY_CODE_COUNT)]


def normalize_recovery_code(code: str) -> str:
    return code.strip().lower().replace(" ", "").replace("-", "")


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(normalize_recovery_code(code).encode()).hexdigest()

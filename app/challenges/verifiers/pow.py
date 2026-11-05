import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.challenges.base import ChallengeVerifier
from app.challenges.registry import register_verifier
from app.challenges.replay import mark_used
from app.core.config import settings
from app.models import Site

_VERSION = "v1"
_MAX_NONCE = 24


class PowConfig(BaseModel):
    bits: int = Field(
        default=16,
        ge=8,
        le=22,
        title="Difficulty (bits)",
        description="Average work is 2^bits hashes: 16 is about 0.15 s on a desktop browser, each +1 doubles it. "
        "Phones can be several times slower, so go above 18 with care.",
    )


def _key() -> bytes:
    # Derived so the token MAC never shares a key with JWTs or IP hashes.
    return hashlib.sha256(b"loupebox-challenge-v1" + settings.jwt_secret.encode()).digest()


def _sign(body: str) -> str:
    return (
        base64.urlsafe_b64encode(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )


def _now() -> datetime:
    return datetime.now(UTC)


def leading_zero_bits(digest: bytes) -> int:
    return len(digest) * 8 - int.from_bytes(digest, "big").bit_length()


def solve(token: str, bits: int) -> str:
    """Reference solver, used by tests; clients implement the same loop. Returns the proof string."""
    nonce = 0
    while leading_zero_bits(hashlib.sha256(f"{token}:{nonce}".encode()).digest()) < bits:
        nonce += 1
    return f"{token}:{nonce}"


@register_verifier
class ProofOfWork(ChallengeVerifier):
    """Stateless signed challenge: the client finds a nonce so sha256("<token>:<nonce>") starts with
    `bits` zero bits. The token binds the site, an expiry and the difficulty; a used-id table makes
    each token single-use."""

    key = "pow"
    label = "Proof of work"
    ConfigModel = PowConfig

    def issue(self, site: Site, config: BaseModel) -> dict[str, Any]:
        assert isinstance(config, PowConfig)
        payload = {
            "r": secrets.token_hex(16),
            "s": str(site.id),
            "e": int((_now() + timedelta(seconds=settings.challenge_ttl_seconds)).timestamp()),
            "b": config.bits,
        }
        body = (
            base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        )
        token = f"{_VERSION}.{body}"
        return {"algorithm": "sha256", "token": f"{token}.{_sign(token)}", "bits": config.bits}

    def verify(self, db: Session, site: Site, config: BaseModel, proof: str) -> bool:
        assert isinstance(config, PowConfig)
        token, _, nonce = proof.rpartition(":")
        if not token or not nonce or len(nonce) > _MAX_NONCE or not nonce.isalnum():
            return False
        signed, _, sig = token.rpartition(".")
        if not hmac.compare_digest(sig, _sign(signed)):
            return False
        version, _, body = signed.partition(".")
        if version != _VERSION:
            return False
        try:
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            salt, site_id, expires, bits = (
                payload["r"],
                uuid.UUID(payload["s"]),
                int(payload["e"]),
                int(payload["b"]),
            )
        except (ValueError, KeyError, TypeError):
            return False
        if site_id != site.id or expires < _now().timestamp():
            return False
        if bits < config.bits:  # difficulty was raised after this token was issued
            return False
        if leading_zero_bits(hashlib.sha256(proof.encode()).digest()) < bits:
            return False
        return mark_used(db, salt, datetime.fromtimestamp(expires, UTC))

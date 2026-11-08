"""The address a customer answers to: replies+<token>@example.com.

The token is the feedback id plus a short HMAC of it, so nothing is stored and nothing can leak from the
database. It routes the mail; it is not the only check (ingest also requires the sender to be the person who
wrote the feedback). Rotating JWT_SECRET only breaks old tokens, and the headers fallback still matches those.
"""

import hashlib
import hmac
import uuid

from app.core.config import settings

MAC_CHARS = 12


def _mac(feedback_id: uuid.UUID) -> str:
    key = hashlib.sha256(b"loupebox-inbound:" + settings.jwt_secret.encode()).digest()
    return hmac.new(key, feedback_id.hex.encode(), hashlib.sha256).hexdigest()[:MAC_CHARS]


def reply_address(feedback_id: uuid.UUID) -> str | None:
    """replies+<token>@example.com for the configured address, or None while inbound email is off."""
    local, _, domain = settings.inbound_address.partition("@")
    if not (local and domain):
        return None
    return f"{local}+{feedback_id.hex}{_mac(feedback_id)}@{domain}"


def feedback_id_from_address(address: str) -> uuid.UUID | None:
    """The feedback id an address carries, or None when it is not one of ours or the token is wrong."""
    local, _, domain = address.strip().lower().rpartition("@")
    base, plus, tag = local.partition("+")
    want_local, _, want_domain = settings.inbound_address.lower().partition("@")
    ours = plus and want_local and base == want_local and domain == want_domain
    if not ours or len(tag) != 32 + MAC_CHARS:
        return None
    try:
        feedback_id = uuid.UUID(hex=tag[:32])
    except ValueError:
        return None
    return feedback_id if hmac.compare_digest(tag[32:], _mac(feedback_id)) else None

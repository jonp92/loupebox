import asyncio
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import bearer, get_current_user, visible_sites
from app.core.events import bus
from app.core.security import access_token_claims
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/events", tags=["events"])

HEARTBEAT_SECONDS = 20  # keeps proxies from closing an idle stream and notices a client that went away


@router.get("")
def stream(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Server-sent events: `{kind, site_id, feedback_id}` whenever feedback of a site the caller can see
    changes. The stream ends when the access token expires; the client reconnects with a fresh one.
    The sites are fixed at connect time, so a new membership shows up on the next reconnect."""
    sites = None if user.is_superadmin else {str(site.id) for site, _ in visible_sites(db, user)}
    expires = access_token_claims(creds.credentials)["exp"]
    db.close()  # a stream can last hours: hand the connection back now

    async def frames() -> AsyncIterator[str]:
        sub = bus.subscribe(sites)
        try:
            yield ": connected\n\n"
            while (left := expires - time.time()) > 0:
                try:
                    yield (await asyncio.wait_for(sub.queue.get(), min(HEARTBEAT_SECONDS, left))).frame()
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(sub)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},  # no-buffering for nginx
    )

import threading
import time

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Site

_TTL_SECONDS = 30


class PublicOriginCache:
    """Union of every active site's allowed origins.

    Browsers send CORS preflights without the API key, so we can't know the site yet. Preflight
    and CORS headers use this union; the route then enforces the exact per-site list.
    """

    def __init__(self) -> None:
        self._origins: set[str] = set()
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def contains(self, origin: str) -> bool:
        with self._lock:
            if time.monotonic() - self._loaded_at > _TTL_SECONDS:
                self._load()
            return origin in self._origins

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0

    def _load(self) -> None:
        with get_sessionmaker()() as db:
            rows = db.scalars(select(Site.allowed_origins).where(Site.is_active.is_(True))).all()
        self._origins = {o for origins in rows for o in origins}
        self._loaded_at = time.monotonic()


public_origins = PublicOriginCache()

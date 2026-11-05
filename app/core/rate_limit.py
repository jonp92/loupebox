import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import settings


class RateLimiter:
    """In-process sliding-window limiter.

    State is per-process: with several workers/instances the effective limit is multiplied.
    Swap this class for a Redis-backed one with the same `hit` / `clear` signatures when scaling out.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int, record: bool = True) -> int:
        """Record a hit (or with `record=False` only check). Returns 0 if allowed, else seconds until a
        slot frees up."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(q[0] + window - now) + 1)
            if record:
                q.append(now)
            if len(self._hits) > 50_000:
                self._prune(now, window)
            return 0

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def _prune(self, now: float, window: int) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window]:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Rightmost entry is the one appended by our own proxy.
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def enforce(key: str, limit: int, window: int, record: bool = True) -> None:
    retry_after = limiter.hit(key, limit, window, record)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )


# Failed passwords per (lowercased) email, from any IP, whether or not it has an account, so the limit
# itself doesn't reveal which emails exist.
def _login_failures(email: str) -> tuple[str, int, int]:
    return f"login-fail:{email}", settings.login_failure_limit, settings.login_failure_window_seconds


def check_login_failures(email: str) -> None:
    enforce(*_login_failures(email), record=False)


def record_login_failure(email: str) -> None:
    limiter.hit(*_login_failures(email))


def clear_login_failures(email: str) -> None:
    limiter.clear(_login_failures(email)[0])

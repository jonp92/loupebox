import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque

import redis
from fastapi import HTTPException, Request

from app.core.config import settings

log = logging.getLogger("loupebox.rate_limit")


class MemoryLimiter:
    """In-process sliding-window limiter.

    State is per-process: with several API replicas the effective limit is multiplied, so those set
    REDIS_URL and get `RedisLimiter`, which has the same `hit` / `clear` / `reset` interface.
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


# The same sliding window as MemoryLimiter, as one atomic step on a sorted set of hit times. It reads the
# Redis server's clock, so replicas with skewed clocks still agree.
_HIT_SCRIPT = """
local key, limit, window = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) >= limit then
  local oldest = tonumber(redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')[2])
  return math.max(1, math.floor(oldest + window - now) + 1)
end
if ARGV[3] == '1' then
  redis.call('ZADD', key, now, ARGV[4])
  redis.call('EXPIRE', key, window)
end
return 0
"""


class RedisLimiter:
    """Sliding-window limiter shared by every API replica through Redis.

    Keys are keyed hashes, so the emails and IPs in them are not stored in Redis. If Redis can't be
    reached the limits fall back to this process's memory for a short while instead of failing open or
    locking everyone out.
    """

    _PREFIX = "loupebox:rl:"
    _RETRY_SECONDS = 5

    def __init__(self, url: str) -> None:
        self._redis = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        self._hit = self._redis.register_script(_HIT_SCRIPT)
        self._fallback = MemoryLimiter()
        self._down_until = 0.0

    def _key(self, key: str) -> str:
        digest = hmac.new(settings.jwt_secret.encode(), f"rl:{key}".encode(), hashlib.sha256)
        return self._PREFIX + digest.hexdigest()

    def _available(self) -> bool:
        return time.monotonic() >= self._down_until

    def _failed(self, error: redis.RedisError) -> None:
        if self._available():
            log.warning("Redis unavailable, rate limits are per process for now: %s", error)
        self._down_until = time.monotonic() + self._RETRY_SECONDS

    def hit(self, key: str, limit: int, window: int, record: bool = True) -> int:
        if self._available():
            try:
                args = [limit, window, int(record), secrets.token_hex(8)]
                return int(self._hit(keys=[self._key(key)], args=args))
            except redis.RedisError as e:
                self._failed(e)
        return self._fallback.hit(key, limit, window, record)

    def clear(self, key: str) -> None:
        self._fallback.clear(key)
        try:
            self._redis.delete(self._key(key))
        except redis.RedisError as e:
            self._failed(e)

    def reset(self) -> None:
        """Forget every limit (tests)."""
        self._fallback.reset()
        keys = list(self._redis.scan_iter(match=self._PREFIX + "*"))
        if keys:
            self._redis.delete(*keys)


limiter = RedisLimiter(settings.redis_url) if settings.redis_url else MemoryLimiter()


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

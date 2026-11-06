import threading
import time
from collections.abc import Callable, Hashable
from typing import TypeVar

T = TypeVar("T")
_MISS = object()


class TTLCache:
    """Keeps computed values for `ttl` seconds. Requests that miss on the same key at once compute it once.

    The cache lives in one process: with several API containers each has its own copy, so after a change made
    through another container a value can be out of date for up to `ttl` seconds. Use it only for values where
    that is fine. Keys are `(site_id, name)` so one site's entries can be dropped together."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._values: dict[tuple[Hashable, str], tuple[float, object]] = {}
        self._locks: dict[tuple[Hashable, str], threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: tuple[Hashable, str], compute: Callable[[], T]) -> T:
        value = self._fresh(key)
        if value is not _MISS:
            return value  # type: ignore[return-value]
        with self._lock_for(key):
            value = self._fresh(key)  # another request may have filled it while this one waited
            if value is _MISS:
                value = compute()
                with self._guard:
                    self._values[key] = (time.monotonic() + self.ttl, value)
            return value  # type: ignore[return-value]

    def invalidate(self, owner: Hashable) -> None:
        """Drop every entry for one owner (a site), for example after its tags changed."""
        with self._guard:
            for key in [k for k in self._values if k[0] == owner]:
                del self._values[key]

    def clear(self) -> None:
        with self._guard:
            self._values.clear()

    def _fresh(self, key: tuple[Hashable, str]) -> object:
        with self._guard:
            entry = self._values.get(key)
        return entry[1] if entry and entry[0] > time.monotonic() else _MISS

    def _lock_for(self, key: tuple[Hashable, str]) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

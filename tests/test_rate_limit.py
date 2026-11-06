"""Both limiter backends behave the same. The Redis ones run when TEST_REDIS_URL is set; each test deletes
the limiter's keys (loupebox:rl:*) in that Redis, so point it at a throwaway one."""

import os
import time

import pytest

from app.core.rate_limit import MemoryLimiter, RedisLimiter

REDIS_URL = os.environ.get("TEST_REDIS_URL", "")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="set TEST_REDIS_URL to test the Redis limiter")


def _redis() -> RedisLimiter:
    limiter = RedisLimiter(REDIS_URL)
    limiter.reset()
    return limiter


@pytest.fixture(params=["memory", pytest.param("redis", marks=needs_redis)])
def limiter(request):
    return MemoryLimiter() if request.param == "memory" else _redis()


def test_allows_up_to_the_limit_then_says_when_to_retry(limiter):
    assert [limiter.hit("k", 3, 60) for _ in range(3)] == [0, 0, 0]
    assert 1 <= limiter.hit("k", 3, 60) <= 61
    assert limiter.hit("other", 3, 60) == 0


def test_check_only_does_not_use_up_the_limit(limiter):
    for _ in range(5):
        assert limiter.hit("k", 1, 60, record=False) == 0
    assert limiter.hit("k", 1, 60) == 0
    assert limiter.hit("k", 1, 60, record=False) > 0


def test_clear_forgets_the_hits(limiter):
    limiter.hit("k", 1, 60)
    limiter.clear("k")
    assert limiter.hit("k", 1, 60) == 0


def test_hits_expire_after_the_window(limiter):
    limiter.hit("k", 1, 1)
    assert limiter.hit("k", 1, 1) > 0
    time.sleep(1.1)
    assert limiter.hit("k", 1, 1) == 0


@needs_redis
def test_replicas_share_one_count():
    a, b = _redis(), RedisLimiter(REDIS_URL)
    assert a.hit("k", 2, 60) == 0
    assert b.hit("k", 2, 60) == 0
    assert a.hit("k", 2, 60) > 0
    b.clear("k")
    assert a.hit("k", 2, 60) == 0


@needs_redis
def test_redis_keys_do_not_contain_emails_or_ips():
    limiter = _redis()
    limiter.hit("login-acct:203.0.113.9:ann@example.com", 5, 60)
    keys = [k.decode() for k in limiter._redis.scan_iter(match="loupebox:rl:*")]
    assert len(keys) == 1
    assert "ann" not in keys[0] and "203.0.113" not in keys[0]


def test_falls_back_to_memory_while_redis_is_down(caplog):
    limiter = RedisLimiter("redis://127.0.0.1:1/0")  # nothing listens on port 1
    assert limiter.hit("k", 2, 60) == 0
    assert limiter.hit("k", 2, 60) == 0
    assert limiter.hit("k", 2, 60) > 0
    limiter.clear("k")
    assert limiter.hit("k", 2, 60) == 0
    warnings = [r for r in caplog.records if "Redis unavailable" in r.getMessage()]
    assert len(warnings) == 1  # once, not on every request

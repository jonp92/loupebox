import asyncio

from app.core.config import settings
from app.db.session import get_engine


def test_postgres_engine_uses_the_configured_pool(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setattr(settings, "db_pool_size", 7)
    monkeypatch.setattr(settings, "db_max_overflow", 3)
    monkeypatch.setattr(settings, "db_pool_timeout", 4)
    engine = get_engine.__wrapped__()  # a fresh engine; the cached one is shared with every other test
    try:
        pool = engine.pool
        assert (pool.size(), pool._max_overflow, pool.timeout()) == (7, 3, 4)
    finally:
        engine.dispose()


def test_concurrency_limit_queues_then_turns_requests_away():
    import httpx

    from app.core.middleware import ConcurrencyLimitMiddleware

    release = asyncio.Event()

    async def slow_app(scope, receive, send):
        if scope["path"] != "/health":
            await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    limited = ConcurrencyLimitMiddleware(slow_app, limit=1, wait_seconds=0.05, exempt=frozenset({"/health"}))

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limited), base_url="http://t") as c:
            first = asyncio.create_task(c.get("/work"))
            await asyncio.sleep(0.01)  # the first request now holds the only slot
            busy = await c.get("/work")
            health = await c.get("/health")
            release.set()
            assert (await first).status_code == 200
            after = await c.get("/work")  # the slot is free again
            return busy, health, after

    busy, health, after = asyncio.run(run())
    assert busy.status_code == 503 and busy.headers["retry-after"] == "5"
    assert health.status_code == 200
    assert after.status_code == 200


def test_origin_lookup_does_not_run_on_the_event_loop(client, monkeypatch):
    """The lookup can hit the database; on the event loop a full pool would freeze the whole server."""
    from app.core.origins import public_origins

    on_loop = []

    def contains(origin):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return True

    monkeypatch.setattr(public_origins, "contains", contains)
    client.options(
        "/feedback",
        headers={"Origin": "https://shop.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert on_loop == [False]

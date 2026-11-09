import asyncio
import json
import threading

import pytest
from sqlalchemy import select

from app.api import event_routes
from app.core import events
from app.core.events import RESYNC, Event, bus, publish
from app.db.session import get_engine, get_sessionmaker
from app.models import Role
from tests.conftest import make_site
from tests.test_bulk_filters import as_role, seed


@pytest.fixture
def local_events(monkeypatch):
    """Deliver straight to the bus, as on SQLite, whatever the test database is."""
    monkeypatch.setattr(events, "_send", lambda evs: [bus.deliver(e) for e in evs])


def received(sub) -> list[Event]:
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


@pytest.mark.usefixtures("local_events")
def test_events_wait_for_the_commit_and_drop_on_rollback(db):
    async def run():
        sub = bus.subscribe(None)
        db.execute(select(1))  # a change in progress: publish is always called inside a transaction
        publish(db, "feedback", "s1", "f1")
        await asyncio.sleep(0.02)
        assert received(sub) == []  # nothing before the commit
        db.rollback()
        db.commit()
        await asyncio.sleep(0.02)
        assert received(sub) == []  # a rolled back change never announces itself
        publish(db, "feedback", "s1", "f1")
        publish(db, "feedback", "s1", "f1")
        db.commit()
        await asyncio.sleep(0.02)
        assert received(sub) == [Event("feedback", "s1", "f1")]  # once, with ids only
        bus.unsubscribe(sub)

    asyncio.run(run())


@pytest.mark.usefixtures("local_events")
def test_changes_through_the_api_are_announced(client, db):
    site = make_site(db, "Shop")
    h = as_role(client, db, site, Role.editor, "ed@example.com")
    item = seed(db, site, message="Broken", email="v@example.org")

    async def run():
        sub = bus.subscribe(None)
        # The client calls block this loop, which is fine: events are queued and read afterwards.
        path = f"/sites/{site.id}/feedback/{item.id}"
        assert client.patch(path, headers=h, json={"status": "read"}).is_success
        assert client.post(f"{path}/notes", headers=h, json={"body": "hi"}).is_success
        await asyncio.sleep(0.05)
        kinds = {(e.kind, e.site_id, e.feedback_id) for e in received(sub)}
        assert kinds == {("feedback", str(site.id), str(item.id)), ("thread", str(site.id), str(item.id))}
        bus.unsubscribe(sub)

    asyncio.run(run())


def test_a_full_queue_becomes_one_resync():
    async def run():
        sub = bus.subscribe(None)
        for i in range(70):
            sub._offer(Event("feedback", "s", str(i)))
        got = received(sub)
        assert got[0] == RESYNC and len(got) < 10  # the backlog was swapped for one resync
        bus.unsubscribe(sub)

    asyncio.run(run())


def test_subscribers_only_see_their_sites():
    async def run():
        mine = bus.subscribe({"a"})
        everyone = bus.subscribe(None)
        for ev in (Event("feedback", "a"), Event("feedback", "b"), RESYNC):
            bus.deliver(ev)
        await asyncio.sleep(0.02)
        assert [e.site_id for e in received(mine)] == ["a", ""]
        assert [e.site_id for e in received(everyone)] == ["a", "b", ""]
        for sub in (mine, everyone):
            bus.unsubscribe(sub)

    asyncio.run(run())


def test_stream_needs_a_token(client):
    assert client.get("/events").status_code == 401


def test_stream_sends_visible_events_then_ends_at_token_expiry(client, db, monkeypatch):
    """The test client reads a response to its end, so the token is made to expire after half a second."""
    import time

    mine, other = make_site(db, "Mine"), make_site(db, "Other")
    h = as_role(client, db, mine, Role.viewer, "v@example.com")
    real = event_routes.access_token_claims
    monkeypatch.setattr(event_routes, "access_token_claims", lambda t: {**real(t), "exp": time.time() + 0.5})

    def announce():
        bus.deliver(Event("feedback", str(other.id), "hidden"))
        bus.deliver(Event("feedback", str(mine.id), "shown"))

    threading.Timer(0.2, announce).start()
    r = client.get("/events", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no"
    frames = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert frames == [{"kind": "feedback", "site_id": str(mine.id), "feedback_id": "shown"}]
    assert get_sessionmaker()  # the connection was handed back, not held for the stream


@pytest.mark.skipif(get_engine().dialect.name != "postgresql", reason="NOTIFY needs Postgres")
def test_postgres_notify_reaches_the_bus(db):
    """What a worker commit looks like to an API process: NOTIFY, then the listener forwards it."""
    stop = events.start_listener()

    async def run():
        sub = bus.subscribe(None)
        await asyncio.sleep(1.5)  # the listener connects, then tells everyone to resync
        received(sub)
        db.execute(select(1))
        publish(db, "thread", "s1", "f1")
        db.commit()
        await asyncio.sleep(1.5)
        assert received(sub) == [Event("thread", "s1", "f1")]
        bus.unsubscribe(sub)

    try:
        asyncio.run(run())
    finally:
        stop.set()

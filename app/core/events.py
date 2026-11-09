"""Live updates for the admin UI: "something changed" events, never the data itself.

`publish()` queues an event on the caller's session and it goes out when that session commits (a rollback
drops it), the same way `audit()` rides on the transaction. The browser reacts by refetching what it shows,
so an event carries ids only and a missed one costs nothing but a stale screen until the next one.

Delivery: on Postgres every event goes through NOTIFY and each API process LISTENs, so events raised in the
worker (an inbound email reply) reach every replica. On SQLite (dev, tests) there is one process and the
event goes straight to the local subscribers. No Redis needed either way.
"""

import asyncio
import contextlib
import json
import logging
import threading
from dataclasses import asdict, dataclass

import psycopg
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_engine

log = logging.getLogger(__name__)

CHANNEL = "loupebox_events"
QUEUE_SIZE = 64


@dataclass(frozen=True)
class Event:
    kind: str  # "feedback": an item or the list changed. "thread": its replies or notes changed.
    site_id: str
    feedback_id: str | None = None

    def frame(self) -> str:
        return f"data: {json.dumps(asdict(self))}\n\n"


# Tells a client to refetch everything: events may have been missed (a full queue, a lost connection).
RESYNC = Event("resync", "")


class Subscriber:
    """One open stream. `sites` is the set of site ids it may see, or None for a superadmin."""

    def __init__(self, sites: set[str] | None) -> None:
        self.sites = sites
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[Event] = asyncio.Queue(QUEUE_SIZE)

    def _offer(self, ev: Event) -> None:  # runs on the event loop
        if ev.kind != "resync" and self.sites is not None and ev.site_id not in self.sites:
            return
        try:
            self.queue.put_nowait(ev)
        except asyncio.QueueFull:  # a client that can't keep up gets one resync instead of the backlog
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(RESYNC)

    def offer(self, ev: Event) -> None:  # any thread
        with contextlib.suppress(RuntimeError):  # the loop is closed: the server is shutting down
            self.loop.call_soon_threadsafe(self._offer, ev)


class Bus:
    """The streams open on this process."""

    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._lock = threading.Lock()

    def subscribe(self, sites: set[str] | None) -> Subscriber:
        sub = Subscriber(sites)
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(sub)

    def deliver(self, ev: Event) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for sub in subscribers:
            sub.offer(ev)


bus = Bus()


def publish(db: Session, kind: str, site_id: object, feedback_id: object | None = None) -> None:
    """Queue an event for when `db` commits. Safe to call twice for the same change."""
    db.info.setdefault("events", set()).add(
        Event(kind, str(site_id), str(feedback_id) if feedback_id else None)
    )


def _send(events: set[Event]) -> None:
    """Hand committed events on. Never raises: the change is already saved, so a failure here only means
    screens stay stale until the next event."""
    try:
        engine = get_engine()
        if engine.dialect.name != "postgresql":
            for ev in events:
                bus.deliver(ev)
            return
        with engine.connect() as conn:
            for ev in events:
                conn.execute(text("SELECT pg_notify(:channel, :payload)"),
                             {"channel": CHANNEL, "payload": json.dumps(asdict(ev))})
            conn.commit()
    except Exception:
        log.warning("Could not send live events", exc_info=True)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if events := session.info.pop("events", None):
        _send(events)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop("events", None)


def _dsn() -> str:
    return make_url(settings.database_url).set(drivername="postgresql").render_as_string(hide_password=False)


def _listen(stop: threading.Event) -> None:
    """Forward every NOTIFY to the local streams; reconnect (and tell clients to resync) if the link drops."""
    while not stop.is_set():
        try:
            with psycopg.connect(_dsn(), autocommit=True) as conn:
                conn.execute(f"LISTEN {CHANNEL}")
                bus.deliver(RESYNC)  # anything sent while we were not listening is lost
                while not stop.is_set():
                    for notice in conn.notifies(timeout=1):
                        try:
                            bus.deliver(Event(**json.loads(notice.payload)))
                        except (ValueError, TypeError):
                            log.warning("Ignored a malformed live event")
        except Exception:
            log.warning("Live event listener lost its connection, retrying", exc_info=True)
            stop.wait(2)


def start_listener() -> threading.Event | None:
    """Start forwarding NOTIFYs on Postgres (call once per API process). Returns the stop flag, or None
    when events are delivered in process."""
    if get_engine().dialect.name != "postgresql":
        return None
    stop = threading.Event()
    threading.Thread(target=_listen, args=(stop,), name="live-events", daemon=True).start()
    return stop

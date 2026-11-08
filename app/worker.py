"""Notification worker: `python -m app.worker`. Polls the outbox and delivers through providers."""

import logging
import signal
import time

from app.challenges.replay import purge_expired
from app.core import health, runtime_settings
from app.core.attachments import sweep_orphans
from app.core.audit import purge_expired as purge_audit
from app.core.config import settings
from app.core.retention import sweep as sweep_retention
from app.db.session import get_sessionmaker
from app.inbound.base import PollingSource
from app.inbound.registry import all_sources, load_sources
from app.models.user import utcnow
from app.notifications.dispatcher import process_due, purge_finished
from app.notifications.registry import load_providers

log = logging.getLogger("loupebox.worker")

_stop = False
PURGE_EVERY = 3600  # seconds between retention sweeps
ORPHAN_EVERY = 86400  # seconds between scans of the attachment store for files with no row


def _request_stop(*_: object) -> None:
    global _stop
    _stop = True


_last_inbound = float("-inf")


def poll_inbound(db) -> int:
    """Ask every configured polling source for mail, at most every IMAP_POLL_SECONDS. One failing mailbox
    must not stop the rest of the pass."""
    global _last_inbound
    if time.monotonic() - _last_inbound < settings.imap_poll_seconds:
        return 0
    _last_inbound = time.monotonic()
    handled = 0
    for source in all_sources():
        if isinstance(source, PollingSource) and source.is_configured():
            try:
                handled += source.poll(db)
            except Exception:
                log.exception("inbound source %s failed", source.key)
    return handled


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    load_providers()
    load_sources()
    log.info("worker started, polling every %ss", settings.worker_poll_seconds)
    last_purge = last_beat = last_orphans = float("-inf")  # everything sweeps at startup
    while not _stop:
        try:
            with get_sessionmaker()() as db:
                runtime_settings.load(db)  # pick up changes made in the admin UI
                handled = process_due(db)
                if time.monotonic() - last_beat >= health.HEARTBEAT_EVERY:
                    last_beat = time.monotonic()
                    health.beat(db, utcnow())
                handled += poll_inbound(db)
                if time.monotonic() - last_purge >= PURGE_EVERY:
                    last_purge = time.monotonic()
                    removed = purge_finished(db, utcnow())
                    if removed:
                        log.info("purged %s finished outbox rows", removed)
                    expired = purge_expired(db, utcnow())
                    if expired:
                        log.info("purged %s expired challenge markers", expired)
                    health.purge_heartbeats(db, utcnow())
                    swept = sweep_retention(db, utcnow())
                    if swept:
                        log.info("retention removed %s feedback items or addresses", swept)
                if time.monotonic() - last_orphans >= ORPHAN_EVERY:
                    last_orphans = time.monotonic()
                    orphans = sweep_orphans(db, utcnow())
                    if orphans:
                        log.info("removed %s attachment files that no feedback refers to", orphans)
                    old_audit = purge_audit(db, utcnow())
                    if old_audit:
                        log.info("purged %s audit events past retention", old_audit)
        except Exception:
            log.exception("worker pass failed")
            handled = 0
        if not handled:  # keep draining without sleeping while there is work
            time.sleep(settings.worker_poll_seconds)
    log.info("worker stopped")


if __name__ == "__main__":
    run()

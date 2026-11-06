"""Notification worker: `python -m app.worker`. Polls the outbox and delivers through providers."""

import logging
import signal
import time

from app.challenges.replay import purge_expired
from app.core import health, runtime_settings
from app.core.audit import purge_expired as purge_audit
from app.core.config import settings
from app.core.retention import sweep as sweep_retention
from app.db.session import get_sessionmaker
from app.models.user import utcnow
from app.notifications.dispatcher import process_due, purge_finished
from app.notifications.registry import load_providers

log = logging.getLogger("loupebox.worker")

_stop = False
PURGE_EVERY = 3600  # seconds between retention sweeps


def _request_stop(*_: object) -> None:
    global _stop
    _stop = True


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    load_providers()
    log.info("worker started, polling every %ss", settings.worker_poll_seconds)
    last_purge = last_beat = float("-inf")  # sweep once at startup, then hourly
    while not _stop:
        try:
            with get_sessionmaker()() as db:
                runtime_settings.load(db)  # pick up changes made in the admin UI
                handled = process_due(db)
                if time.monotonic() - last_beat >= health.HEARTBEAT_EVERY:
                    last_beat = time.monotonic()
                    health.beat(db, utcnow())
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

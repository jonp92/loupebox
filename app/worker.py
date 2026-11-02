"""Notification worker: `python -m app.worker`. Polls the outbox and delivers through providers."""

import logging
import signal
import time

from app.core.config import settings
from app.db.session import get_sessionmaker
from app.notifications.dispatcher import process_due
from app.notifications.registry import load_providers

log = logging.getLogger("ganymede.worker")

_stop = False


def _request_stop(*_: object) -> None:
    global _stop
    _stop = True


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    load_providers()
    log.info("worker started, polling every %ss", settings.worker_poll_seconds)
    while not _stop:
        try:
            with get_sessionmaker()() as db:
                handled = process_due(db)
        except Exception:
            log.exception("worker pass failed")
            handled = 0
        if not handled:  # keep draining without sleeping while there is work
            time.sleep(settings.worker_poll_seconds)
    log.info("worker stopped")


if __name__ == "__main__":
    run()

"""Read a shared mailbox over IMAP. The worker calls `poll` on a timer; nothing is sent from here."""

import imaplib
import logging
import re
import ssl
from collections import Counter

from sqlalchemy.orm import Session

from app.core.config import settings
from app.inbound.base import Outcome, PollingSource
from app.inbound.ingest import ingest
from app.inbound.mime import parse_message
from app.inbound.registry import register_source

log = logging.getLogger("loupebox.inbound.imap")

BATCH = 50  # messages per pass, so one huge mailbox cannot hold the worker
TIMEOUT = 30
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")


def _connect() -> imaplib.IMAP4:
    """The one place a connection is opened (tests replace it, like the mail transports)."""
    if settings.imap_security == "ssl":
        conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            settings.imap_host, settings.imap_port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT
        )
    else:
        conn = imaplib.IMAP4(settings.imap_host, settings.imap_port, timeout=TIMEOUT)
        if settings.imap_security == "starttls":
            conn.starttls(ssl_context=ssl.create_default_context())
    conn.login(settings.imap_username, settings.imap_password)
    return conn


def _size(conn: imaplib.IMAP4, uid: bytes) -> int:
    _, data = conn.uid("FETCH", uid, "(RFC822.SIZE)")
    match = _SIZE.search(b" ".join(d if isinstance(d, bytes) else d[0] for d in data if d))
    return int(match.group(1)) if match else 0


@register_source
class ImapSource(PollingSource):
    key = "imap"
    label = "IMAP mailbox"

    def is_configured(self) -> bool:
        if not (settings.imap_host and settings.inbound_address):
            return False
        # Never send a password in the clear.
        return not (settings.imap_security == "none" and settings.imap_username)

    def poll(self, db: Session) -> Counter[Outcome]:
        conn = _connect()
        outcomes: Counter[Outcome] = Counter()
        try:
            conn.select(settings.imap_folder)
            _, found = conn.uid("SEARCH", None, "UNSEEN")
            for uid in (found[0].split() if found and found[0] else [])[:BATCH]:
                if _size(conn, uid) > settings.inbound_max_bytes:
                    log.warning("skipped a message larger than INBOUND_MAX_BYTES")
                else:
                    _, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                    try:
                        parsed = parse_message(data[0][1])
                    except Exception:
                        log.exception("could not read one message; skipping it")  # unreadable: never retry
                    else:
                        try:
                            outcome = ingest(db, parsed)
                            db.commit()
                            outcomes[outcome] += 1
                        except Exception:
                            db.rollback()
                            log.exception("could not store one message; it stays unread and is retried")
                            continue
                # Seen whether it was stored, ignored or skipped, so it is never fetched twice.
                conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        finally:
            try:
                conn.logout()
            except Exception:  # the connection may already be gone; nothing to clean up
                log.debug("imap logout failed", exc_info=True)
        return outcomes

from datetime import timedelta

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.models import (
    Feedback,
    NotificationChannel,
    NotificationOutbox,
    OutboxStatus,
    Role,
)
from app.models.user import utcnow
from app.notifications import registry
from app.notifications.base import Message, NotificationProvider, SendResult
from app.notifications.dispatcher import LEASE, RETRY_DELAYS, process_due
from app.db.session import get_engine
from tests.conftest import SITE_ORIGIN, make_site

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}


class FakeConfig(BaseModel):
    prefix: str = ""


class FakeProvider(NotificationProvider):
    key = "fake"
    label = "Fake"
    ConfigModel = FakeConfig

    def __init__(self):
        self.sent: list[Message] = []
        self.results: list[SendResult] = []
        self.configured = True

    def is_configured(self) -> bool:
        return self.configured

    def send(self, message, config):
        self.sent.append(message)
        return self.results.pop(0) if self.results else SendResult.sent("m-1")


@pytest.fixture
def fake(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setitem(registry._providers, "fake", provider)
    return provider


def make_channel(db, site, **kw) -> NotificationChannel:
    channel = NotificationChannel(
        site_id=site.id,
        provider=kw.pop("provider", "fake"),
        name="ops",
        events=kw.pop("events", ["feedback.created"]),
        extra_recipients=kw.pop("extra_recipients", ["ops@example.com"]),
        min_role=Role.admin,
        **kw,
    )
    db.add(channel)
    db.commit()
    return channel


def submit(client, message="hello"):
    return client.post("/feedback", json={"message": message}, headers=HEADERS)


def outbox(db) -> list[NotificationOutbox]:
    db.expire_all()
    return list(db.scalars(select(NotificationOutbox)))


def make_due(db, row):
    row.next_attempt_at = utcnow() - timedelta(seconds=1)
    db.commit()


def test_submit_enqueues_for_subscribed_enabled_channels_only(client, db, fake):
    site = make_site(db)
    make_channel(db, site)
    make_channel(db, site, enabled=False)
    make_channel(db, site, events=[])

    assert submit(client).status_code == 201

    rows = outbox(db)
    assert len(rows) == 1
    assert rows[0].status == OutboxStatus.pending
    assert rows[0].payload["excerpt"] == "hello"
    assert rows[0].payload["feedback_id"] == str(db.scalar(select(Feedback.id)))


def test_nothing_queued_for_spam_duplicates_or_honeypot(client, db, fake):
    make_channel(db, make_site(db))

    client.post("/feedback", json={"message": "bot", "website": "x"}, headers=HEADERS)
    submit(client, "http://a http://b http://c http://d")  # quarantined as spam
    assert outbox(db) == []

    submit(client, "same")
    submit(client, "same")  # duplicate
    assert len(outbox(db)) == 1


def test_no_channels_means_no_rows(client, db):
    make_site(db)
    assert submit(client).status_code == 201
    assert outbox(db) == []


def test_enqueue_failure_rolls_back_the_feedback(client, db, fake, monkeypatch):
    make_channel(db, make_site(db))

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.api.public_routes.enqueue_feedback_created", boom)
    with pytest.raises(RuntimeError):
        submit(client)
    db.expire_all()
    assert db.scalar(select(Feedback.id)) is None


def test_worker_sends_and_records_message_id(client, db, fake):
    make_channel(db, make_site(db))
    submit(client)

    assert process_due(db) == 1

    row = outbox(db)[0]
    assert (row.status, row.attempts, row.provider_message_id) == (OutboxStatus.sent, 1, "m-1")
    assert row.sent_at is not None
    assert fake.sent[0].to == ["ops@example.com"]
    assert fake.sent[0].subject == "New feedback on Shop"
    assert process_due(db) == 0  # nothing left


def test_retry_follows_backoff_schedule_then_fails(client, db, fake):
    make_channel(db, make_site(db))
    submit(client)
    fake.results = [SendResult.retry("503")] * (len(RETRY_DELAYS) + 1)

    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        before = utcnow()
        assert process_due(db) == 1
        row = outbox(db)[0]
        assert (row.status, row.attempts, row.last_error) == (OutboxStatus.pending, attempt, "503")
        # next_attempt_at round-trips naive on SQLite
        due = row.next_attempt_at.replace(tzinfo=before.tzinfo)
        assert before + delay <= due <= utcnow() + delay
        assert process_due(db) == 0  # not due yet
        make_due(db, row)

    assert process_due(db) == 1
    row = outbox(db)[0]
    assert (row.status, row.attempts) == (OutboxStatus.failed, len(RETRY_DELAYS) + 1)
    assert process_due(db) == 0


def test_permanent_failure_is_not_retried(client, db, fake):
    make_channel(db, make_site(db))
    submit(client)
    fake.results = [SendResult.failed("401 bad key")]

    process_due(db)

    row = outbox(db)[0]
    assert (row.status, row.attempts, row.last_error) == (OutboxStatus.failed, 1, "401 bad key")


@pytest.mark.parametrize("how", ["disabled", "deleted", "unconfigured", "no_recipients", "bad_config"])
def test_unsendable_rows_fail_without_calling_provider(client, db, fake, how):
    site = make_site(db)
    channel = make_channel(db, site)
    submit(client)
    if how == "disabled":
        channel.enabled = False
    elif how == "deleted":
        db.delete(channel)
    elif how == "unconfigured":
        fake.configured = False
    elif how == "no_recipients":
        channel.extra_recipients = []
    else:
        channel.config = {"prefix": 5}
    db.commit()

    process_due(db)

    row = outbox(db)[0]
    assert row.status == OutboxStatus.failed
    assert row.last_error
    assert fake.sent == []


@pytest.mark.skipif(get_engine().dialect.name == "sqlite", reason="SQLite does not enforce ON DELETE")
def test_deleting_a_channel_keeps_its_log(client, db, fake):
    channel = make_channel(db, make_site(db))
    submit(client)
    db.delete(channel)
    db.commit()
    assert [r.channel_id for r in outbox(db)] == [None]


def test_provider_exception_becomes_a_retry(client, db, fake, monkeypatch):
    make_channel(db, make_site(db))
    submit(client)

    def boom(*a):
        raise ValueError("kaput")

    monkeypatch.setattr(fake, "send", boom)
    process_due(db)

    row = outbox(db)[0]
    assert (row.status, row.last_error) == (OutboxStatus.pending, "ValueError: kaput")


def test_stuck_sending_row_is_reclaimed_after_lease(client, db, fake):
    make_channel(db, make_site(db))
    submit(client)
    row = outbox(db)[0]
    # Simulate a crashed worker: claimed, never reported back.
    row.status = OutboxStatus.sending
    row.attempts = 1
    row.next_attempt_at = utcnow() + LEASE
    db.commit()
    assert process_due(db) == 0  # lease still running

    make_due(db, row)
    assert process_due(db) == 1
    row = outbox(db)[0]
    assert (row.status, row.attempts) == (OutboxStatus.sent, 2)


def test_long_error_text_is_truncated(client, db, fake):
    make_channel(db, make_site(db))
    submit(client)
    fake.results = [SendResult.failed("x" * 5000)]
    process_due(db)
    assert len(outbox(db)[0].last_error) == 500

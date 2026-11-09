from datetime import timedelta

import pytest

from app.core import health
from app.core.rate_limit import MemoryLimiter, RedisLimiter
from app.models import NotificationChannel, NotificationOutbox, OutboxStatus, Role, WorkerHeartbeat
from app.models.user import utcnow
from tests.conftest import add_member, login, make_site, make_user


@pytest.fixture
def h(client, db):
    make_user(db, "root@example.com", superadmin=True)
    return login(client, "root@example.com")


def row(db, site, status, **kw):
    db.add(NotificationOutbox(site_id=site.id, event_type="feedback.created", status=status, **kw))
    db.commit()


def test_superadmin_only(client, db):
    assert client.get("/system/health").status_code in (401, 403)
    owner = make_user(db, "own@example.com")
    add_member(db, owner, make_site(db), Role.admin)
    assert client.get("/system/health", headers=login(client, "own@example.com")).status_code == 403


def test_idle_instance_without_a_worker(client, h):
    body = client.get("/system/health", headers=h).json()
    assert body["database"] == "ok"
    assert body["worker"] == {"status": "error", "last_beat_at": None, "live": 0}
    assert body["outbox"]["status"] == "ok"  # nothing queued, so nothing is stuck


def test_beat_makes_the_worker_ok_and_goes_stale(client, h, db):
    health.beat(db, utcnow())
    assert client.get("/system/health", headers=h).json()["worker"]["status"] == "ok"
    db.query(WorkerHeartbeat).update({"beat_at": utcnow() - health.WORKER_STALE - timedelta(seconds=1)})
    db.commit()
    worker = client.get("/system/health", headers=h).json()["worker"]
    assert worker["status"] == "error" and worker["live"] == 0 and worker["last_beat_at"]


def test_beat_updates_one_row_and_purge_drops_old_ones(db):
    health.beat(db, utcnow())
    health.beat(db, utcnow())
    assert db.query(WorkerHeartbeat).count() == 1
    db.add(WorkerHeartbeat(name="gone", beat_at=utcnow() - health.HEARTBEAT_KEEP - timedelta(hours=1)))
    db.commit()
    assert health.purge_heartbeats(db, utcnow()) == 1


def test_outbox_counts_and_stuck_detection(client, h, db):
    site = make_site(db)
    row(db, site, OutboxStatus.pending, next_attempt_at=utcnow() - timedelta(seconds=90))
    row(db, site, OutboxStatus.pending, next_attempt_at=utcnow() + timedelta(hours=1))  # not due yet
    row(db, site, OutboxStatus.held)
    row(db, site, OutboxStatus.failed)
    row(db, site, OutboxStatus.failed, created_at=utcnow() - timedelta(days=2))  # outside 24 h
    box = client.get("/system/health", headers=h).json()["outbox"]
    assert (box["pending"], box["held"], box["failed_24h"]) == (2, 1, 1)
    assert 85 <= box["oldest_due_seconds"] <= 120
    assert box["status"] == "error"  # work is queued and no worker is beating
    health.beat(db, utcnow())
    assert client.get("/system/health", headers=h).json()["outbox"]["status"] == "warn"  # a failure remains


def test_failures_list_newest_first_with_context(client, h, db):
    site = make_site(db, "Shop")
    channel = NotificationChannel(site_id=site.id, provider="webhook", name="Ops hook")
    db.add(channel)
    db.commit()
    now = utcnow()
    row(
        db,
        site,
        OutboxStatus.failed,
        channel_id=channel.id,
        attempts=4,
        last_error="old",
        created_at=now - timedelta(hours=3),
    )
    row(
        db,
        site,
        OutboxStatus.failed,
        channel_id=channel.id,
        attempts=1,
        last_error="new",
        created_at=now - timedelta(hours=1),
    )
    row(
        db, site, OutboxStatus.failed, last_error="orphan", created_at=now - timedelta(hours=2)
    )  # channel deleted
    row(db, site, OutboxStatus.failed, last_error="ancient", created_at=now - timedelta(days=2))
    row(db, site, OutboxStatus.pending, last_error="retrying")
    failures = client.get("/system/health", headers=h).json()["outbox"]["recent_failures"]
    assert [f["error"] for f in failures] == ["new", "orphan", "old"]
    assert failures[0] | {"queued_at": None} == {
        "site": "Shop",
        "channel": "Ops hook",
        "provider": "webhook",
        "queued_at": None,
        "attempts": 1,
        "error": "new",
    }
    assert failures[1]["channel"] is None and failures[1]["provider"] is None


def test_failures_are_capped(client, h, db):
    site = make_site(db)
    for _ in range(health.FAILURES_SHOWN + 3):
        row(db, site, OutboxStatus.failed, last_error="x")
    box = client.get("/system/health", headers=h).json()["outbox"]
    assert (
        box["failed_24h"] == health.FAILURES_SHOWN + 3
        and len(box["recent_failures"]) == health.FAILURES_SHOWN
    )


def test_failure_errors_hide_url_secrets_and_stay_short(client, h, db):
    leaky = "POST https://user:hunter2@hooks.example.com/services/T0/B0/secret-path?token=abc failed"
    row(db, make_site(db), OutboxStatus.failed, last_error=leaky, payload={"text": "feedback words"})
    row(db, make_site(db, "Two"), OutboxStatus.failed, last_error="z" * 500)
    resp = client.get("/system/health", headers=h)
    errors = [f["error"] for f in resp.json()["outbox"]["recent_failures"]]
    assert "POST https://hooks.example.com failed" in errors
    assert max(map(len, errors)) == health.ERROR_SHOWN
    for hidden in ("hunter2", "secret-path", "token=abc", "feedback words"):
        assert hidden not in resp.text


def test_redis_is_reported_only_when_configured(client, h, monkeypatch):
    monkeypatch.setattr(health, "limiter", MemoryLimiter())  # CI's Postgres leg runs with REDIS_URL set
    assert client.get("/system/health", headers=h).json()["redis"] is None
    stub = object.__new__(RedisLimiter)
    monkeypatch.setattr(health, "limiter", stub)
    for up, expected in ((True, "ok"), (False, "warn")):
        monkeypatch.setattr(RedisLimiter, "ping", lambda self, up=up: up)
        assert client.get("/system/health", headers=h).json()["redis"] == expected


def test_checklist_follows_the_install(client, h, db, monkeypatch):
    def items():
        return {i["id"]: i["done"] for i in client.get("/system/health", headers=h).json()["checklist"]}

    monkeypatch.setattr(health, "mail_provider", lambda: None)
    monkeypatch.setattr(health.settings, "public_url", "")
    assert items() == dict.fromkeys(["mail", "public_url", "worker", "site", "channel"], False)

    monkeypatch.setattr(health, "mail_provider", lambda: object())
    monkeypatch.setattr(health.settings, "public_url", "https://feedback.example.com")
    health.beat(db, utcnow())
    site = make_site(db)
    assert items() == {"mail": True, "public_url": True, "worker": True, "site": True, "channel": False}

    off = NotificationChannel(site_id=site.id, provider="webhook", name="Off", enabled=False)
    db.add(off)
    db.commit()
    assert items()["channel"] is False  # a disabled channel doesn't count
    off.enabled = True
    db.commit()
    assert items()["channel"] is True


# -- inbound email ----------------------------------------------------------------------------------------


@pytest.fixture
def imap_on(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "inbound_address", "replies@example.com")
    monkeypatch.setattr(settings, "imap_host", "imap.test")
    monkeypatch.setattr(settings, "imap_poll_seconds", 60)


def inbound(client, h):
    return client.get("/system/health", headers=h).json()["inbound"]


def test_no_inbound_row_while_inbound_email_is_off(client, h):
    assert inbound(client, h) == []


def test_inbound_row_walks_from_not_read_yet_to_ok_to_error_to_stale(client, h, db, imap_on):
    (row,) = inbound(client, h)
    assert row["source"] == "imap" and row["status"] == "warn" and row["last_ok_at"] is None  # never polled

    now = utcnow()
    health.record_poll(db, "imap", now)
    assert inbound(client, h)[0]["status"] == "ok"

    later = now + timedelta(seconds=30)
    health.record_poll(db, "imap", later, "IMAP4.error: [AUTHENTICATIONFAILED] bad login")
    row = inbound(client, h)[0]
    assert row["status"] == "error" and "AUTHENTICATIONFAILED" in row["last_error"]

    health.record_poll(db, "imap", utcnow() + timedelta(seconds=40))  # it recovered: the error clears
    row = inbound(client, h)[0]
    assert row["status"] == "ok" and row["last_error"] is None

    db.query(health.InboundStatus).update(
        {"last_ok_at": utcnow() - timedelta(minutes=10), "last_error_at": None}
    )
    db.commit()
    assert inbound(client, h)[0]["status"] == "warn"  # worker stopped: not read for a while


def test_a_slow_poll_interval_widens_the_stale_window(client, h, db, imap_on, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "imap_poll_seconds", 3600)
    health.record_poll(db, "imap", utcnow() - timedelta(minutes=30))
    assert inbound(client, h)[0]["status"] == "ok"


def test_recorded_errors_drop_urls_and_are_shortened(db):
    health.record_poll(db, "imap", utcnow(), "oops https://user:pw@mail.test/path?token=x " + "z" * 500)
    error = db.get(health.InboundStatus, "imap").last_error
    assert "pw" not in error and "token" not in error and len(error) <= 200


def poll(db, at, **found):
    from collections import Counter

    from app.inbound.base import Outcome

    health.record_poll(db, "imap", at, outcomes=Counter({Outcome(k): n for k, n in found.items()}))


def test_row_counts_what_happened_to_the_mail_in_the_last_day(client, h, db, imap_on):
    now = utcnow()
    poll(db, now - timedelta(hours=30), stored=9)  # older than a day: not counted, but it was the last stored
    poll(db, now - timedelta(hours=2), stored=1, unmatched=1)
    poll(db, now - timedelta(hours=2), stored=2, bounced=1, ignored=5, duplicate=4)  # same hour: added up
    poll(db, now, ignored=1)
    row = inbound(client, h)[0]
    assert row["counts"] == {
        "stored": 3,
        "unmatched": 1,
        "bounced": 1,
        "ignored": 6,
    }  # duplicates carry no news
    assert row["last_stored_at"] and row["status"] == "ok"


def test_unmatched_mail_piling_up_warns_until_something_is_stored(client, h, db, imap_on):
    now = utcnow()
    poll(db, now, unmatched=2)
    assert inbound(client, h)[0]["status"] == "ok"
    poll(db, now, unmatched=1, ignored=9)
    row = inbound(client, h)[0]
    assert row["status"] == "warn" and row["counts"]["unmatched"] == 3  # robots are not what is piling up
    poll(db, now, stored=1)  # an answer got through: the matching works
    assert inbound(client, h)[0]["status"] == "ok"


def test_old_buckets_are_dropped_when_new_ones_are_written(db):
    now = utcnow()
    poll(db, now - timedelta(hours=30), stored=1)
    poll(db, now, stored=1)
    assert len(db.get(health.InboundStatus, "imap").counts) == 1

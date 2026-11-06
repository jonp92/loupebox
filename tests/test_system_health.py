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

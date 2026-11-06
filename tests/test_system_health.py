from datetime import timedelta

import pytest

from app.core import health
from app.core.rate_limit import RedisLimiter
from app.models import NotificationOutbox, OutboxStatus, Role, WorkerHeartbeat
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


def test_health_never_exposes_payloads_or_errors(client, h, db):
    failed = OutboxStatus.failed
    row(db, make_site(db), failed, last_error="smtp password was hunter2", payload={"text": "secret"})
    text = client.get("/system/health", headers=h).text
    assert "hunter2" not in text and "secret" not in text


def test_redis_is_reported_only_when_configured(client, h, monkeypatch):
    assert client.get("/system/health", headers=h).json()["redis"] is None  # memory limiter
    stub = object.__new__(RedisLimiter)
    monkeypatch.setattr(health, "limiter", stub)
    for up, expected in ((True, "ok"), (False, "warn")):
        monkeypatch.setattr(RedisLimiter, "ping", lambda self, up=up: up)
        assert client.get("/system/health", headers=h).json()["redis"] == expected

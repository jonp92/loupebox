import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import retention
from app.models import (
    AuditEvent,
    Feedback,
    FeedbackNote,
    FeedbackReply,
    NotificationOutbox,
    OutboxStatus,
    Role,
)
from tests.conftest import add_member, login, make_site, make_user, read_zip

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def seed(db, site, age_days, **kw) -> Feedback:
    item = Feedback(
        site_id=site.id, content_hash="h", ip_hash="i", created_at=ago(age_days), **{"message": "hello", **kw}
    )
    db.add(item)
    db.commit()
    return item


def outbox(db, site, age_days, status=OutboxStatus.sent, **payload) -> None:
    db.add(
        NotificationOutbox(
            site_id=site.id,
            event_type="feedback.created",
            payload=payload,
            status=status,
            created_at=ago(age_days),
        )
    )
    db.commit()


def messages(db, site) -> list[str]:
    db.expire_all()
    return sorted(db.scalars(select(Feedback.message).where(Feedback.site_id == site.id)))


# --- the sweep -----------------------------------------------------------------------------------


def test_delete_after_n_days_only_for_the_site_that_asks(db):
    site, other, unset = make_site(db, "A"), make_site(db, "B"), make_site(db, "C")
    site.retention_delete_days = 30
    other.retention_delete_days = 90
    db.commit()
    for s in (site, other, unset):
        seed(db, s, 10, message="new")
        seed(db, s, 60, message="mid")
        seed(db, s, 120, message="old")
    assert retention.sweep(db, NOW) == 2 + 1
    assert messages(db, site) == ["new"]
    assert messages(db, other) == ["mid", "new"]
    assert messages(db, unset) == ["mid", "new", "old"]  # no setting keeps everything


def test_the_boundary_day_is_kept(db):
    site = make_site(db, retention_delete_days=30)
    seed(db, site, 29.9, message="inside")
    seed(db, site, 30.1, message="outside")
    retention.sweep(db, NOW)
    assert messages(db, site) == ["inside"]


def test_strip_email_keeps_the_item_and_resets_the_dedupe_hash(db):
    site = make_site(db, retention_strip_email_days=30)
    old = seed(db, site, 40, message="old", email="a@example.com", name="Ann")
    new = seed(db, site, 5, message="new", email="b@example.com")
    assert retention.sweep(db, NOW) == 1
    db.expire_all()
    assert (old.email, old.content_hash, old.message, old.name) == (None, "", "old", "Ann")
    assert (new.email, new.content_hash) == ("b@example.com", "h")


def test_both_rules_together(db):
    site = make_site(db, retention_delete_days=90, retention_strip_email_days=30)
    seed(db, site, 100, message="gone", email="a@example.com")
    stripped = seed(db, site, 40, message="stripped", email="b@example.com")
    kept = seed(db, site, 5, message="kept", email="c@example.com")
    retention.sweep(db, NOW)
    db.expire_all()
    assert messages(db, site) == ["kept", "stripped"]
    assert (stripped.email, kept.email) == (None, "c@example.com")


def test_large_backlog_is_cleared_in_batches(db, monkeypatch):
    monkeypatch.setattr(retention, "BATCH", 2)
    site = make_site(db, retention_delete_days=30, retention_strip_email_days=10)
    for i in range(5):
        seed(db, site, 100, message=f"old{i}")
    for i in range(5):
        seed(db, site, 20, message=f"mid{i}", email="a@example.com")
    retention.sweep(db, NOW)
    db.expire_all()
    assert messages(db, site) == [f"mid{i}" for i in range(5)]
    assert db.scalars(select(Feedback.email).where(Feedback.email.is_not(None))).all() == []
    assert retention.sweep(db, NOW) == 0  # nothing left to do: a second hour is a no-op


def test_outbox_copies_go_with_the_shortest_rule(db):
    site = make_site(db, retention_delete_days=90, retention_strip_email_days=30)
    outbox(db, site, 40, email="a@example.com")  # finished and past the 30 days
    outbox(db, site, 40, OutboxStatus.pending, email="b@example.com")  # still to be sent
    outbox(db, site, 5, email="c@example.com")
    retention.sweep(db, NOW)
    db.expire_all()
    left = sorted(r.payload["email"] for r in db.scalars(select(NotificationOutbox)))
    assert left == ["b@example.com", "c@example.com"]


def test_the_sweep_is_audited_with_counts_only(db):
    site = make_site(db, retention_delete_days=30, retention_strip_email_days=10)
    seed(db, site, 100, message="secret text", email="a@example.com")
    seed(db, site, 20, message="more", email="b@example.com")
    retention.sweep(db, NOW)
    (event,) = db.scalars(select(AuditEvent).where(AuditEvent.action == "retention.sweep")).all()
    assert (event.actor_email, event.actor_id, event.site_id) == ("system", None, site.id)
    assert event.details == {"deleted": 1, "emails_stripped": 1, "notifications": 0}
    assert "example.com" not in json.dumps(event.details) + event.summary
    assert retention.sweep(db, NOW) == 0
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "retention.sweep")).all() == [event]


def test_a_cascade_removes_replies_and_notes(db):
    if db.get_bind().dialect.name == "sqlite":
        pytest.skip("SQLite does not enforce the foreign-key cascade")
    site = make_site(db, retention_delete_days=30)
    item = seed(db, site, 100)
    db.add_all(
        [
            FeedbackNote(feedback_id=item.id, body="n"),
            FeedbackReply(feedback_id=item.id, body="r", status="sent"),
        ]
    )
    db.commit()
    retention.sweep(db, NOW)
    assert db.scalars(select(FeedbackNote)).all() == [] and db.scalars(select(FeedbackReply)).all() == []


# --- the settings --------------------------------------------------------------------------------


@pytest.fixture
def admin(client, db):
    site = make_site(db)
    add_member(db, make_user(db, "a@example.com"), site, Role.admin)
    return site, login(client, "a@example.com")


def test_settings_roundtrip_and_clear(client, db, admin):
    site, h = admin
    url = f"/sites/{site.id}"
    assert client.get(url, headers=h).json()["retention_delete_days"] is None
    r = client.patch(url, json={"retention_delete_days": 90, "retention_strip_email_days": 30}, headers=h)
    assert (r.json()["retention_delete_days"], r.json()["retention_strip_email_days"]) == (90, 30)
    r = client.patch(url, json={"retention_strip_email_days": None}, headers=h)  # explicit null: off
    assert (r.json()["retention_delete_days"], r.json()["retention_strip_email_days"]) == (90, None)
    r = client.patch(url, json={"name": "Renamed"}, headers=h)  # leaving the field out changes nothing
    assert r.json()["retention_delete_days"] == 90
    diff = db.scalars(select(AuditEvent).where(AuditEvent.action == "site.update")).all()[0].details
    assert diff["retention_delete_days"] == {"from": None, "to": 90}


@pytest.mark.parametrize(
    "body", [{"retention_delete_days": 0}, {"retention_delete_days": -1}, {"retention_delete_days": 99_999}]
)
def test_settings_reject_nonsense_days(client, admin, body):
    site, h = admin
    assert client.patch(f"/sites/{site.id}", json=body, headers=h).status_code == 422


def test_an_address_cannot_outlive_its_item(client, admin):
    site, h = admin
    client.patch(f"/sites/{site.id}", json={"retention_delete_days": 30}, headers=h)
    r = client.patch(f"/sites/{site.id}", json={"retention_strip_email_days": 60}, headers=h)
    assert r.status_code == 422
    assert client.get(f"/sites/{site.id}", headers=h).json()["retention_strip_email_days"] is None
    r = client.patch(
        f"/sites/{site.id}", json={"retention_delete_days": 20, "retention_strip_email_days": 20}, headers=h
    )
    assert r.status_code == 200


def test_editors_cannot_change_retention(client, db):
    site = make_site(db)
    add_member(db, make_user(db, "e@example.com"), site, Role.editor)
    h = login(client, "e@example.com")
    assert client.patch(f"/sites/{site.id}", json={"retention_delete_days": 1}, headers=h).status_code == 403


# --- one person's data ---------------------------------------------------------------------------


def person(site, op, email="Ann@Example.com"):
    return f"/sites/{site.id}/privacy/{op}", {"email": email}


def test_lookup_counts_every_case_and_status_of_the_address(client, db, admin):
    site, h = admin
    seed(db, site, 1, email="ann@example.com")
    seed(db, site, 1, email="ANN@example.com", status="spam")
    seed(db, site, 1, email="bob@example.com")
    seed(db, make_site(db, "Other"), 1, email="ann@example.com")
    url, body = person(site, "lookup")
    assert client.post(url, json=body, headers=h).json() == {"items": 2}


def test_export_has_everything_about_the_address(client, db, admin):
    site, h = admin
    mine = seed(db, site, 3, email="ann@example.com", name="Ann", message="hi", meta={"k": "v"})
    seed(db, site, 1, email="bob@example.com", message="not hers")
    db.add_all(
        [
            FeedbackNote(feedback_id=mine.id, body="internal"),
            FeedbackReply(feedback_id=mine.id, body="thanks", status="sent"),
        ]
    )
    db.commit()
    url, body = person(site, "export")
    r = client.post(url, json=body, headers=h)
    assert r.headers["content-disposition"] == 'attachment; filename="person-export.zip"'
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["cache-control"] == "no-store"
    assert int(r.headers["content-length"]) == len(r.content)
    files = read_zip(r.content)
    assert list(files) == ["data.json"]  # a person with no images: just the description
    data = json.loads(files["data.json"])
    (item,) = data["items"]
    assert (item["message"], item["name"], item["email"], item["metadata"]) == (
        "hi",
        "Ann",
        "ann@example.com",
        {"k": "v"},
    )
    assert [n["body"] for n in item["notes"]] == ["internal"]
    assert [(x["body"], x["status"]) for x in item["replies"]] == [("thanks", "sent")]
    assert b"not hers" not in r.content and b"bob@example.com" not in r.content


def test_erase_removes_the_items_and_outbox_copies_and_nothing_else(client, db, admin):
    site, h = admin
    other = make_site(db, "Other")
    seed(db, site, 1, email="ann@example.com", message="a1")
    seed(db, site, 1, email="ANN@Example.com", message="a2", status="spam")
    seed(db, site, 1, email="bob@example.com", message="b")
    seed(db, other, 1, email="ann@example.com", message="elsewhere")
    outbox(db, site, 1, OutboxStatus.pending, email="ann@example.com", excerpt="a1")
    outbox(db, site, 1, email="bob@example.com")
    outbox(db, other, 1, email="ann@example.com")
    url, body = person(site, "erase")
    assert client.post(url, json=body, headers=h).json() == {"deleted": 2}
    assert messages(db, site) == ["b"] and messages(db, other) == ["elsewhere"]
    left = sorted((r.site_id == site.id, r.payload["email"]) for r in db.scalars(select(NotificationOutbox)))
    assert left == [(False, "ann@example.com"), (True, "bob@example.com")]
    assert client.post(url, json=body, headers=h).json() == {"deleted": 0}  # idempotent


def test_audit_records_counts_never_the_address(client, db, admin):
    site, h = admin
    seed(db, site, 1, email="ann@example.com")
    for op in ("lookup", "export", "erase"):
        url, body = person(site, op)
        client.post(url, json=body, headers=h)
    events = db.scalars(select(AuditEvent).where(AuditEvent.action.like("privacy.%"))).all()
    assert sorted(e.action for e in events) == ["privacy.erase", "privacy.export"]  # lookup changes nothing
    for e in events:
        assert e.details == ({"items": 1, "images": 0} if e.action == "privacy.export" else {"items": 1})
        assert "ann" not in json.dumps(e.details) + e.summary + e.site_name.lower()


def test_only_admins_and_members_can_use_it(client, db, admin):
    site, _ = admin
    add_member(db, make_user(db, "ed@example.com"), site, Role.editor)
    make_user(db, "stranger@example.com")
    for op in ("lookup", "export", "erase"):
        url, body = person(site, op)
        assert client.post(url, json=body, headers=login(client, "ed@example.com")).status_code == 403
        assert client.post(url, json=body, headers=login(client, "stranger@example.com")).status_code == 404
        assert client.post(url, json=body).status_code == 401


def test_a_bad_address_is_rejected(client, admin):
    site, h = admin
    assert (
        client.post(f"/sites/{site.id}/privacy/erase", json={"email": "nope"}, headers=h).status_code == 422
    )

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.audit import purge_expired
from app.core.config import settings
from app.models import AuditEvent, Feedback, Role
from tests.conftest import add_member, login, make_site, make_user
from tests.test_notifications import fake  # noqa: F401  (fixture: registers the "fake" provider)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PASSWORD = "a-brand-new-password-1"


@pytest.fixture
def root(client, db):
    user = make_user(db, "root@example.com", superadmin=True)
    return user, login(client, "root@example.com")


def events(db, action=None):
    db.expire_all()
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)).all()
    return [e for e in rows if action is None or e.action == action]


def one(db, action):
    (event,) = events(db, action)
    return event


# --- what gets recorded -------------------------------------------------------------------------


def test_user_lifecycle_is_recorded(client, db, root):
    _, h = root
    r = client.post(
        "/users",
        json={"first_name": "B", "last_name": "B", "email": "Bob@E.com", "password": PASSWORD},
        headers=h,
    )
    bob = r.json()["id"]
    created = one(db, "user.create")
    assert (created.actor_email, created.target_id, created.target_type) == ("root@example.com", bob, "user")
    assert created.details == {"email": "bob@e.com", "is_superadmin": False}

    client.patch(f"/users/{bob}", json={"is_superadmin": True}, headers=h)
    client.patch(f"/users/{bob}", json={"is_superadmin": False}, headers=h)
    client.patch(f"/users/{bob}", json={"is_active": False}, headers=h)
    client.patch(f"/users/{bob}", json={"is_active": True}, headers=h)
    client.patch(f"/users/{bob}", json={"first_name": "Robert", "email": "robert@e.com"}, headers=h)
    client.patch(f"/users/{bob}", json={"password": PASSWORD + "2"}, headers=h)
    client.put(f"/users/{bob}/avatar", content=PNG, headers={**h, "Content-Type": "image/png"})
    client.delete(f"/users/{bob}/avatar", headers=h)

    assert [e.action for e in events(db)] == [
        "user.create",
        "user.promote",
        "user.demote",
        "user.disable",
        "user.enable",
        "user.update",
        "user.password_reset",
        "user.avatar_set",
        "user.avatar_clear",
    ]
    update = one(db, "user.update")
    assert update.details == {
        "first_name": {"from": "B", "to": "Robert"},
        "email": {"from": "bob@e.com", "to": "robert@e.com"},
    }
    # Summaries are snapshots: they name the account as it was then, not as it is renamed later.
    assert one(db, "user.promote").summary == "Made bob@e.com a superadmin"
    assert one(db, "user.demote").summary == "Removed superadmin from bob@e.com"


def test_site_member_and_channel_changes_are_recorded(client, db, root, fake):
    _, h = root
    site = client.post(
        "/sites", json={"name": "Shop", "allowed_origins": ["https://a.com"]}, headers=h
    ).json()
    sid, url = site["id"], f"/sites/{site['id']}"
    bob = make_user(db, "bob@e.com")

    client.patch(url, json={"name": "Shop 2", "daily_limit": 5, "challenge_mode": "pow"}, headers=h)
    client.patch(url, json={"name": "Shop 2"}, headers=h)  # no change: not logged
    client.post(f"{url}/rotate-key", headers=h)
    client.put(f"{url}/members", json={"email": "bob@e.com", "role": "viewer"}, headers=h)
    client.put(f"{url}/members", json={"email": "bob@e.com", "role": "viewer"}, headers=h)  # no change
    client.put(f"{url}/members", json={"email": "bob@e.com", "role": "editor"}, headers=h)
    client.delete(f"{url}/members/{bob.id}", headers=h)
    ch = client.post(
        f"{url}/notifications",
        json={"provider": "fake", "name": "Ops", "extra_recipients": ["x@e.com"]},
        headers=h,
    ).json()
    client.patch(
        f"{url}/notifications/{ch['id']}", json={"name": "Ops2", "extra_recipients": ["y@e.com"]}, headers=h
    )
    client.delete(f"{url}/notifications/{ch['id']}", headers=h)

    assert [e.action for e in events(db)] == [
        "site.create",
        "site.update",
        "site.rotate_key",
        "member.add",
        "member.role_change",
        "member.remove",
        "channel.create",
        "channel.update",
        "channel.delete",
    ]
    assert all(e.site_id and e.site_name for e in events(db))
    update = one(db, "site.update")
    assert update.details["name"] == {"from": "Shop", "to": "Shop 2"}
    assert update.details["daily_limit"]["to"] == 5 and update.details["challenge_mode"]["to"] == "pow"
    assert one(db, "member.role_change").details["role"] == {"from": "viewer", "to": "editor"}
    assert one(db, "channel.update").details == {
        "name": {"from": "Ops", "to": "Ops2"},
        "extra_recipients": "changed",
    }
    assert sid == str(one(db, "site.create").site_id)


def test_feedback_delete_and_self_password_change_are_recorded(client, db):
    site = make_site(db)
    add_member(db, make_user(db, "a@e.com"), site, Role.admin)
    h = login(client, "a@e.com")
    fb = Feedback(site_id=site.id, message="private words", content_hash="h", ip_hash="i", meta={})
    db.add(fb)
    db.commit()
    fb_id = str(fb.id)
    client.delete(f"/sites/{site.id}/feedback/{fb_id}", headers=h)
    client.post(
        "/auth/me/password",
        json={"current_password": "correct-horse-battery", "new_password": PASSWORD},
        headers=h,
    )

    deleted = one(db, "feedback.delete")
    assert deleted.target_id == fb_id and deleted.details == {"status": "new"}
    assert one(db, "auth.password_change").details == {"password": "changed"}


def test_site_delete_keeps_its_history(client, db, root):
    _, h = root
    sid = client.post("/sites", json={"name": "Gone", "allowed_origins": []}, headers=h).json()["id"]
    assert client.delete(f"/sites/{sid}", headers=h).status_code == 204
    gone = one(db, "site.delete")
    assert gone.site_name == "Gone" and str(gone.site_id) == sid
    assert [e.action for e in events(db)] == ["site.create", "site.delete"]  # create row survived the cascade


# --- what must never be recorded ----------------------------------------------------------------


def test_secrets_and_content_never_reach_the_log(client, db, root, fake):
    _, h = root
    site = client.post("/sites", json={"name": "Shop", "allowed_origins": []}, headers=h).json()
    url = f"/sites/{site['id']}"
    old_key = site["public_key"]
    new_key = client.post(f"{url}/rotate-key", headers=h).json()["public_key"]
    bob = client.post(
        "/users",
        json={"first_name": "B", "last_name": "B", "email": "b@e.com", "password": PASSWORD},
        headers=h,
    ).json()
    client.patch(f"/users/{bob['id']}", json={"password": PASSWORD + "x"}, headers=h)
    client.post(
        f"{url}/notifications",
        json={"provider": "fake", "name": "Ops", "config": {"secret": "s3cret-token"}},
        headers=h,
    )
    blob = json.dumps([[e.summary, e.details] for e in events(db)])
    for secret in (PASSWORD, PASSWORD + "x", old_key, new_key, "s3cret-token"):
        assert secret not in blob


# --- atomicity ----------------------------------------------------------------------------------


def test_failed_changes_leave_no_event(client, db, root):
    me, h = root
    body = {"first_name": "B", "last_name": "B", "email": "root@example.com", "password": PASSWORD}
    assert client.post("/users", json=body, headers=h).status_code == 409  # duplicate email
    assert (
        client.patch(f"/users/{me.id}", json={"is_superadmin": False}, headers=h).status_code == 400
    )  # self-demote
    other = make_user(db, "o@e.com")
    assert (
        client.put(
            f"/users/{other.id}/avatar", content=b"nope", headers={**h, "Content-Type": "image/png"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/auth/me/password",
            json={"current_password": "wrong-password-1", "new_password": PASSWORD},
            headers=h,
        ).status_code
        == 400
    )
    assert events(db) == []


# --- reading the log ----------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.viewer, Role.editor, Role.admin])
def test_only_superadmins_can_read_the_log(client, db, role):
    site = make_site(db)
    add_member(db, make_user(db, "u@e.com"), site, role)
    assert client.get("/audit", headers=login(client, "u@e.com")).status_code == 403
    assert client.get("/audit").status_code == 401


def test_filters_search_and_paging(client, db, root, fake):
    _, h = root
    s1 = client.post("/sites", json={"name": "Alpha", "allowed_origins": []}, headers=h).json()["id"]
    client.post("/sites", json={"name": "Beta", "allowed_origins": []}, headers=h)
    client.post(f"/sites/{s1}/rotate-key", headers=h)
    make_user(db, "other@e.com", superadmin=True)
    client.patch(f"/sites/{s1}", json={"daily_limit": 3}, headers=login(client, "other@e.com"))

    def get(**params):
        return client.get("/audit", params=params, headers=h).json()

    everything = get()
    assert everything["total"] == 4 and everything["items"][0]["action"] == "site.update"  # newest first
    assert get(group="site")["total"] == 4 and get(group="user")["total"] == 0
    assert get(action="site.rotate_key")["total"] == 1
    assert client.get("/audit/actions", headers=h).json() == ["site.create", "site.rotate_key", "site.update"]
    assert get(site_id=s1)["total"] == 3
    assert get(q="beta")["total"] == 1 and get(q="OTHER@")["total"] == 1
    assert get(q="%")["total"] == 0  # LIKE wildcards are escaped
    assert get(actor_id=everything["items"][0]["actor_id"])["total"] == 1
    page = get(limit=2, offset=3)
    assert page["total"] == 4 and len(page["items"]) == 1
    assert client.get("/audit", params={"group": "a;b"}, headers=h).status_code == 422


# --- retention ----------------------------------------------------------------------------------


def test_retention_purges_old_events_and_zero_keeps_everything(db, monkeypatch):
    now = datetime.now(UTC)
    for name, age in (("old", 400), ("recent", 10)):
        db.add(
            AuditEvent(
                created_at=now - timedelta(days=age),
                actor_email="a@e.com",
                action="x.y",
                target_type="t",
                target_id=name,
                summary=name,
                details={},
            )
        )
    db.commit()
    monkeypatch.setattr(settings, "audit_retention_days", 0)
    assert purge_expired(db, now) == 0
    monkeypatch.setattr(settings, "audit_retention_days", 365)
    assert purge_expired(db, now) == 1
    assert [e.target_id for e in events(db)] == ["recent"]

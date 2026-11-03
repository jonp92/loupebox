from datetime import timedelta

from app.models import Feedback, Role
from app.models.user import utcnow
from tests.conftest import add_member, login, make_site, make_user


def fb(db, site, message="hi", status="new", age_hours=0):
    db.add(Feedback(
        site_id=site.id, message=message, content_hash=message, ip_hash="i", meta={}, status=status,
        created_at=utcnow() - timedelta(hours=age_hours),
    ))
    db.commit()


def test_dashboard_counts_only_unread_on_visible_sites(client, db):
    a, b, hidden = make_site(db, "A"), make_site(db, "B"), make_site(db, "Hidden")
    user = make_user(db, "u@example.com")
    add_member(db, user, a, Role.viewer)
    add_member(db, user, b, Role.editor)
    fb(db, a, "a1")
    fb(db, a, "a2", age_hours=48)
    fb(db, a, "read", status="read")
    fb(db, a, "junk", status="spam")
    fb(db, b, "b1")
    fb(db, hidden, "secret")
    r = client.get("/dashboard", headers=login(client, "u@example.com")).json()
    assert (r["new_total"], r["new_24h"], r["sites_with_new"]) == (3, 2, 2)
    assert {s["name"]: s["new_count"] for s in r["sites"]} == {"A": 2, "B": 1}
    assert {s["name"]: s["my_role"] for s in r["sites"]} == {"A": "viewer", "B": "editor"}
    assert r["recent_new"][0]["message"] in {"a1", "b1"}
    assert {i["message"] for i in r["recent_new"]} == {"a1", "a2", "b1"}
    assert "secret" not in str(r)


def test_dashboard_recent_is_newest_first_and_limited(client, db):
    site = make_site(db)
    for i in range(5):
        fb(db, site, f"m{i}", age_hours=i)
    make_user(db, "root@example.com", superadmin=True)
    r = client.get("/dashboard?limit=3", headers=login(client, "root@example.com")).json()
    assert [i["message"] for i in r["recent_new"]] == ["m0", "m1", "m2"]
    assert r["new_total"] == 5
    assert r["recent_new"][0]["site_name"] == "Shop"


def test_dashboard_empty_and_requires_auth(client, db):
    make_user(db, "u@example.com")
    r = client.get("/dashboard", headers=login(client, "u@example.com")).json()
    assert r == {"new_total": 0, "new_24h": 0, "sites_with_new": 0, "sites": [], "recent_new": [],
                 "assigned_total": 0, "assigned": []}
    assert client.get("/dashboard").status_code == 401

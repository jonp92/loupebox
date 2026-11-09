from datetime import timedelta

from app.models import Feedback, Role
from app.models.user import utcnow
from tests.conftest import add_member, login, make_site, make_user


def fb(db, site, message="hi", status="new", age_hours=0):
    db.add(
        Feedback(
            site_id=site.id,
            message=message,
            content_hash=message,
            ip_hash="i",
            meta={},
            status=status,
            created_at=utcnow() - timedelta(hours=age_hours),
        )
    )
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
    assert (r["new_total"], r["sites_with_new"]) == (3, 2)
    assert r["received"] == 4  # a1, a2, read, b1: spam and the hidden site are excluded
    assert r["spam"] == 1
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
    assert r == {
        "days": 7,
        "received": 0,
        "received_previous": 0,
        "received_today": 0,
        "spam": 0,
        "oldest_unread_at": None,
        "series": [0] * 7,
        "new_total": 0,
        "sites_with_new": 0,
        "sites": [],
        "recent_new": [],
        "assigned_total": 0,
        "assigned": [],
    }
    assert client.get("/dashboard").status_code == 401


def test_dashboard_window_series_previous_and_oldest_unread(client, db):
    a, b = make_site(db, "A"), make_site(db, "B")
    make_user(db, "root@example.com", superadmin=True)
    h = login(client, "root@example.com")
    fb(db, a, "today")
    fb(db, a, "today2", status="read")
    fb(db, b, "b-today")
    fb(db, a, "yesterday", status="archived", age_hours=30)
    fb(db, a, "last-week", age_hours=24 * 9)  # previous window for 7, inside 30
    fb(db, a, "old", age_hours=24 * 40)  # outside both for 7 and 30
    r = client.get("/dashboard", headers=h).json()
    assert r["days"] == 7 and len(r["series"]) == 7
    assert (r["received"], r["received_previous"], r["received_today"]) == (4, 1, 3)
    assert r["series"][-1] == 3 and sum(r["series"]) == 4
    by_site = {s["name"]: s["series"] for s in r["sites"]}
    assert sum(by_site["A"]) == 3 and sum(by_site["B"]) == 1 and len(by_site["B"]) == 7
    assert r["oldest_unread_at"] is not None
    month = client.get("/dashboard?window=30", headers=h).json()
    assert (month["received"], month["received_previous"]) == (5, 1) and len(month["series"]) == 30
    assert client.get("/dashboard?window=5", headers=h).status_code == 422

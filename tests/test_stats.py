from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.models import Feedback, Role, SiteStat
from tests.conftest import SITE_ORIGIN, add_member, login, make_site, make_user

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}


def post(client, body=None, headers=None):
    return client.post("/feedback", json=body or {"message": "hi"}, headers=headers or HEADERS)


def counts(db) -> dict[str, int]:
    return {s.kind: s.count for s in db.scalars(select(SiteStat))}


def test_each_drop_reason_is_counted(client, db, monkeypatch):
    site = make_site(db, daily_limit=3)

    post(client, {"message": "bot", "website": "http://x"})
    post(client, {"message": "bot", "website": "http://x"})
    post(client, {"message": "same"})
    post(client, {"message": "same"})
    post(client, headers={"X-API-Key": "pk_test_Shop", "Origin": "https://evil.example"})
    post(client, headers={"X-API-Key": "pk_test_Shop"})  # no Origin
    post(client, {"message": "two"})
    post(client, {"message": "three"})  # 3rd stored -> next hits the daily cap
    post(client, {"message": "four"})
    assert counts(db) == {"honeypot": 2, "duplicate": 1, "origin_denied": 2, "daily_limit": 1}

    monkeypatch.setattr(settings, "public_key_limit", 1)
    post(client, {"message": "x1"})
    post(client, {"message": "x2"})
    assert counts(db)["rate_limited"] >= 1
    assert all(s.site_id == site.id for s in db.scalars(select(SiteStat)))


def test_unknown_key_is_not_attributable(client, db):
    make_site(db)
    post(client, headers={"X-API-Key": "pk_nope", "Origin": SITE_ORIGIN})
    assert counts(db) == {}


def test_stats_endpoint_aggregates_and_zero_fills(client, db):
    site = make_site(db)
    make_user(db, "root@example.com", superadmin=True)
    h = login(client, "root@example.com")
    now = datetime.now(UTC)
    db.add_all([
        Feedback(site_id=site.id, message="a", content_hash="1", ip_hash="i", meta={}, created_at=now),
        Feedback(site_id=site.id, message="b", content_hash="2", ip_hash="i", meta={}, created_at=now),
        Feedback(site_id=site.id, message="s", content_hash="3", ip_hash="i", meta={}, status="spam", created_at=now),
        Feedback(site_id=site.id, message="old", content_hash="4", ip_hash="i", meta={}, created_at=now - timedelta(days=2)),
        Feedback(site_id=site.id, message="ancient", content_hash="5", ip_hash="i", meta={}, created_at=now - timedelta(days=40)),
    ])
    db.commit()
    post(client, {"message": "bot", "website": "x"})

    r = client.get(f"/sites/{site.id}/stats", params={"days": 7}, headers=h)
    assert r.status_code == 200
    days = r.json()["days"]
    assert len(days) == 7
    assert days[-1]["day"] == now.date().isoformat()
    assert days == sorted(days, key=lambda d: d["day"])
    today, two_ago, other = days[-1], days[-3], days[0]
    assert (today["accepted"], today["quarantined"], today["honeypot"]) == (2, 1, 1)
    assert two_ago["accepted"] == 1 and two_ago["quarantined"] == 0
    assert sum(v for k, v in other.items() if k != "day") == 0
    assert sum(d["accepted"] for d in days) == 3  # the 40-day-old item is excluded


def test_stats_scoped_by_site_and_role(client, db):
    a, b = make_site(db, "A"), make_site(db, "B")
    viewer = make_user(db, "v@example.com")
    add_member(db, viewer, a, Role.viewer)
    h = login(client, "v@example.com")
    assert client.get(f"/sites/{a.id}/stats", headers=h).status_code == 200
    assert client.get(f"/sites/{b.id}/stats", headers=h).status_code == 404
    assert client.get(f"/sites/{a.id}/stats", params={"days": 0}, headers=h).status_code == 422
    assert client.get(f"/sites/{a.id}/stats", params={"days": 91}, headers=h).status_code == 422
    assert client.get(f"/sites/{a.id}/stats").status_code == 401

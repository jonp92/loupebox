from app.api import feedback_routes
from app.models import Feedback

from .conftest import login, make_site, make_user


def _site_with(db, client, count: int):
    user = make_user(db, "root@example.com", superadmin=True)
    site = make_site(db)
    db.add_all(
        Feedback(site_id=site.id, message=f"message {i}", content_hash=str(i), ip_hash="ip")
        for i in range(count)
    )
    db.commit()
    return site, login(client, user.email)


def _page(client, site, headers, **params):
    r = client.get(f"/sites/{site.id}/feedback", params=params, headers=headers)
    assert r.status_code == 200
    return r.json()


def test_total_is_exact_below_the_cap(client, db, monkeypatch):
    monkeypatch.setattr(feedback_routes, "TOTAL_CAP", 10)
    site, headers = _site_with(db, client, 7)
    page = _page(client, site, headers)
    assert (page["total"], page["total_capped"]) == (7, False)


def test_total_stops_at_the_cap_and_says_so(client, db, monkeypatch):
    monkeypatch.setattr(feedback_routes, "TOTAL_CAP", 5)
    site, headers = _site_with(db, client, 8)
    page = _page(client, site, headers, limit=2)
    assert (page["total"], page["total_capped"], len(page["items"])) == (5, True, 2)


def test_exactly_the_cap_is_not_reported_as_capped(client, db, monkeypatch):
    monkeypatch.setattr(feedback_routes, "TOTAL_CAP", 5)
    site, headers = _site_with(db, client, 5)
    assert _page(client, site, headers)["total_capped"] is False


def test_paging_past_the_cap_keeps_counting_to_the_end_of_the_page(client, db, monkeypatch):
    monkeypatch.setattr(feedback_routes, "TOTAL_CAP", 5)
    site, headers = _site_with(db, client, 8)
    page = _page(client, site, headers, limit=2, offset=6)
    assert (page["total"], page["total_capped"], len(page["items"])) == (8, False, 2)
    deeper = _page(client, site, headers, limit=2, offset=4)  # more rows follow this page
    assert (deeper["total"], deeper["total_capped"]) == (6, True)

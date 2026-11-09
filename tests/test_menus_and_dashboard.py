import threading
import time
from datetime import timedelta

from app.api import feedback_routes
from app.core.cache import TTLCache
from app.models import Feedback, FeedbackStatus, FeedbackTag
from app.models.user import utcnow

from .conftest import login, make_site, make_user


def _add(db, site, n: int, status=FeedbackStatus.new, age=timedelta(0), prefix="m") -> list[Feedback]:
    items = [
        Feedback(
            site_id=site.id,
            message=f"{prefix} {i}",
            content_hash=f"{site.id}{prefix}{status.value}{i}",
            ip_hash="ip",
            status=status,
            created_at=utcnow() - age - timedelta(seconds=i),
        )
        for i in range(n)
    ]
    db.add_all(items)
    db.commit()
    return items


def _root(db, client):
    return login(client, make_user(db, "root@example.com", superadmin=True).email)


def test_quick_tab_counts_stop_at_the_cap(client, db, monkeypatch):
    monkeypatch.setattr(feedback_routes, "TOTAL_CAP", 5)
    site = make_site(db)
    _add(db, site, 8)
    counts = client.get(f"/sites/{site.id}/feedback/counts", headers=_root(db, client)).json()
    assert counts == {"mine": 0, "mine_capped": False, "unassigned": 5, "unassigned_capped": True}


def test_tag_menu_is_cached_and_dropped_when_tags_change(client, db):
    site = make_site(db)
    item = _add(db, site, 1)[0]
    headers = _root(db, client)
    url = f"/sites/{site.id}/feedback"
    assert client.get(f"{url}/tags", headers=headers).json() == []
    db.add(FeedbackTag(feedback_id=item.id, tag="sneaky"))  # a change made behind the API's back
    db.commit()
    assert client.get(f"{url}/tags", headers=headers).json() == []  # still the cached answer
    client.patch(f"{url}/{item.id}", json={"tags": ["bug"]}, headers=headers)
    assert client.get(f"{url}/tags", headers=headers).json() == [{"tag": "bug", "count": 1}]


def test_cache_entries_expire(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    cache, calls = TTLCache(30), []

    def compute():
        calls.append(1)
        return len(calls)

    assert [cache.get(("a", "x"), compute) for _ in range(3)] == [1, 1, 1]
    clock[0] += 31
    assert cache.get(("a", "x"), compute) == 2
    cache.invalidate("a")
    assert cache.get(("a", "x"), compute) == 3


def test_requests_that_miss_together_compute_once():
    cache, calls = TTLCache(30), []

    def compute():
        calls.append(1)
        time.sleep(0.05)
        return "value"

    threads = [threading.Thread(target=cache.get, args=(("s", "k"), compute)) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1


def test_dashboard_counts_and_newest_unread_span_the_sites(client, db):
    a, b, c = make_site(db, "A"), make_site(db, "B"), make_site(db, "C")
    _add(db, a, 4, prefix="a")
    _add(db, b, 3, prefix="b", age=timedelta(hours=30))  # unread, but not from the last 24 h
    _add(db, c, 2, status=FeedbackStatus.spam, prefix="c")
    _add(db, c, 2, status=FeedbackStatus.read, prefix="c")
    body = client.get("/dashboard", params={"limit": 5}, headers=_root(db, client)).json()
    assert (body["new_total"], body["received"], body["sites_with_new"]) == (
        7,
        9,  # spam is not counted
        2,
    )
    assert [i["message"] for i in body["recent_new"]] == ["a 0", "a 1", "a 2", "a 3", "b 0"]
    new_counts = {s["name"]: s["new_count"] for s in body["sites"]}
    assert new_counts == {"A": 4, "B": 3, "C": 0}

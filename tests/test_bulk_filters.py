import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AuditEvent, Feedback, FeedbackStatus, Role
from tests.conftest import add_member, login, make_site, make_user


def seed(db, site, **kw) -> Feedback:
    item = Feedback(site_id=site.id, content_hash="h", ip_hash="i", **{"message": "hello", **kw})
    db.add(item)
    db.commit()
    return item


def as_role(client, db, site, role: Role, email="u@example.com"):
    add_member(db, make_user(db, email), site, role)
    return login(client, email)


def listed(client, site, h, qs=""):
    r = client.get(f"/sites/{site.id}/feedback{qs}", headers=h)
    assert r.status_code == 200, r.text
    return {i["message"] for i in r.json()["items"]}


def test_filters_rating_email_and_dates(client, db):
    site = make_site(db)
    h = as_role(client, db, site, Role.viewer)
    at = lambda d: datetime(2026, 3, d, 12, tzinfo=UTC)  # noqa: E731
    seed(db, site, message="a", rating=5, email="a@x.com", created_at=at(1))
    seed(db, site, message="b", rating=3, email=None, created_at=at(10))
    seed(db, site, message="c", rating=5, email="", created_at=at(20))
    assert listed(client, site, h, "?rating=5") == {"a", "c"}
    assert listed(client, site, h, "?has_email=true") == {"a"}
    assert listed(client, site, h, "?has_email=false") == {"b", "c"}
    assert listed(client, site, h, "?created_from=2026-03-10") == {"b", "c"}
    assert listed(client, site, h, "?created_to=2026-03-10") == {"a", "b"}  # inclusive of the whole day
    assert listed(client, site, h, "?created_from=2026-03-02&created_to=2026-03-19") == {"b"}
    assert listed(client, site, h, "?rating=5&has_email=true&created_to=2026-03-05") == {"a"}


@pytest.mark.parametrize("qs", ["?rating=0", "?rating=6", "?created_from=nope", "?has_email=maybe"])
def test_bad_filter_values_rejected(client, db, qs):
    site = make_site(db)
    h = as_role(client, db, site, Role.viewer)
    assert client.get(f"/sites/{site.id}/feedback{qs}", headers=h).status_code == 422


def test_export_uses_new_filters(client, db):
    site = make_site(db)
    h = as_role(client, db, site, Role.viewer)
    seed(db, site, message="keep", rating=4)
    seed(db, site, message="drop", rating=1)
    r = client.get(f"/sites/{site.id}/feedback/export.csv?rating=4", headers=h)
    text = r.content.decode("utf-8-sig")
    assert "keep" in text and "drop" not in text


def bulk(client, site, h, **body):
    return client.post(f"/sites/{site.id}/feedback/bulk", headers=h, json=body)


def test_bulk_set_status(client, db):
    site = make_site(db)
    h = as_role(client, db, site, Role.editor)
    items = [seed(db, site, message=str(n)) for n in range(3)]
    r = bulk(client, site, h, ids=[str(i.id) for i in items[:2]], action="set_status", status="archived")
    assert r.status_code == 200 and r.json() == {"affected": 2, "skipped": 0}
    db.expire_all()
    assert [i.status for i in items] == [FeedbackStatus.archived, FeedbackStatus.archived, FeedbackStatus.new]


def test_bulk_skips_other_sites_and_unknown_ids(client, db):
    site, other = make_site(db), make_site(db, "Other")
    h = as_role(client, db, site, Role.editor)
    mine, theirs = seed(db, site), seed(db, other)
    r = bulk(client, site, h, ids=[str(mine.id), str(theirs.id), str(uuid.uuid4())], action="set_status", status="read")
    assert r.json() == {"affected": 1, "skipped": 2}
    db.expire_all()
    assert theirs.status == FeedbackStatus.new


def test_bulk_delete_needs_admin_and_is_audited(client, db):
    site = make_site(db)
    items = [seed(db, site, message="secret text") for _ in range(2)]
    ids = [str(i.id) for i in items]
    editor = as_role(client, db, site, Role.editor)
    assert bulk(client, site, editor, ids=ids, action="delete").status_code == 403
    assert db.scalar(select(Feedback).where(Feedback.id == items[0].id)) is not None
    admin = as_role(client, db, site, Role.admin, "adm@example.com")
    assert bulk(client, site, admin, ids=ids, action="delete").json() == {"affected": 2, "skipped": 0}
    db.expire_all()
    assert db.scalars(select(Feedback)).all() == []
    [event] = db.scalars(select(AuditEvent).where(AuditEvent.action == "feedback.bulk_delete")).all()
    assert event.details["count"] == 2 and "secret" not in str(event.details)


def test_bulk_viewer_forbidden(client, db):
    site = make_site(db)
    h = as_role(client, db, site, Role.viewer)
    item = seed(db, site)
    assert bulk(client, site, h, ids=[str(item.id)], action="set_status", status="read").status_code == 403


def test_bulk_validation(client, db, monkeypatch):
    site = make_site(db)
    h = as_role(client, db, site, Role.admin)
    one = str(uuid.uuid4())
    assert bulk(client, site, h, ids=[], action="delete").status_code == 422
    assert bulk(client, site, h, ids=[one], action="set_status").status_code == 422  # no status
    assert bulk(client, site, h, ids=[one], action="delete", status="read").status_code == 422
    assert bulk(client, site, h, ids=[one], action="explode").status_code == 422
    monkeypatch.setattr(settings, "bulk_max_ids", 2)
    assert bulk(client, site, h, ids=[str(uuid.uuid4()) for _ in range(3)], action="delete").status_code == 422

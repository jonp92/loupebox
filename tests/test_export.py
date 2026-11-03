import csv
import io

import pytest
from sqlalchemy import select

from app.api.feedback_routes import CSV_COLUMNS, csv_cell
from app.core.config import settings
from app.models import AuditEvent, Feedback, FeedbackStatus, Role
from tests.conftest import add_member, login, make_site, make_user


def seed(db, site, **kw) -> Feedback:
    item = Feedback(site_id=site.id, content_hash="h", ip_hash="i", **{"message": "hello", **kw})
    db.add(item)
    db.commit()
    return item


def parse(response) -> list[dict]:
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM
    text = response.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


@pytest.fixture
def viewer(client, db):
    site = make_site(db, "My Shop & Co")
    add_member(db, make_user(db, "v@example.com"), site, Role.viewer)
    return site, login(client, "v@example.com")


def url(site, qs=""):
    return f"/sites/{site.id}/feedback/export.csv{qs}"


@pytest.mark.parametrize(
    "value,expected",
    [("=1+1", "'=1+1"), ("+44 20", "'+44 20"), ("-2", "'-2"), ("@SUM(A1)", "'@SUM(A1)"), ("\tx", "'\tx"),
     ("\rx", "'\rx"), ("safe", "safe"), ("a=b", "a=b"), ("", ""), (5, 5), (None, None)],
)
def test_formula_neutralising(value, expected):
    assert csv_cell(value) == expected


def test_export_contents_and_headers(client, db, viewer):
    site, h = viewer
    seed(db, site, message='He said "hi",\nthen left', name="Zoë", email="z@example.com", rating=5,
         page_url="https://shop.example.com/p?a=1", meta={"k": "v"})
    r = client.get(url(site), headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith('attachment; filename="feedback-my-shop-co-')
    [row] = parse(r)
    assert list(row) == list(CSV_COLUMNS)
    assert row["message"] == 'He said "hi",\nthen left' and row["name"] == "Zoë"
    assert row["rating"] == "5" and row["status"] == "new" and row["meta"] == '{"k":"v"}'
    assert row["created_at"].endswith("Z")


def test_untrusted_text_cannot_become_a_formula(client, db, viewer):
    site, h = viewer
    seed(db, site, message="=HYPERLINK(\"http://evil\",\"x\")", name="+cmd|' /C calc'!A0", email="@evil.com")
    [row] = parse(client.get(url(site), headers=h))
    for col in ("message", "name", "email"):
        assert row[col].startswith("'"), col


def test_filters_match_the_list(client, db, viewer):
    site, h = viewer
    seed(db, site, message="apple pie")
    seed(db, site, message="banana split", status=FeedbackStatus.archived)
    seed(db, site, message="apple spam", status=FeedbackStatus.spam)
    msgs = lambda qs: sorted(r["message"] for r in parse(client.get(url(site, qs), headers=h)))
    assert msgs("") == ["apple pie", "banana split"]  # spam excluded by default, like the list
    assert msgs("?status=spam") == ["apple spam"]
    assert msgs("?q=apple") == ["apple pie"]
    assert msgs("?status=archived&q=banana") == ["banana split"]


def test_only_this_sites_feedback(client, db, viewer):
    site, h = viewer
    seed(db, site, message="mine")
    seed(db, make_site(db, "Other"), message="theirs")
    assert [r["message"] for r in parse(client.get(url(site), headers=h))] == ["mine"]


def test_empty_export_is_just_the_header(client, db, viewer):
    site, h = viewer
    r = client.get(url(site), headers=h)
    assert r.status_code == 200 and parse(r) == []
    assert r.content.decode("utf-8-sig").strip() == ",".join(CSV_COLUMNS)


def test_row_cap(client, db, viewer, monkeypatch):
    site, h = viewer
    for i in range(5):
        seed(db, site, message=f"m{i}")
    monkeypatch.setattr(settings, "export_max_rows", 3)
    assert len(parse(client.get(url(site), headers=h))) == 3


def test_large_export_streams_all_rows(client, db, viewer):
    site, h = viewer
    db.add_all(Feedback(site_id=site.id, content_hash="h", ip_hash="i", message=f"m{i}") for i in range(1203))
    db.commit()
    assert len(parse(client.get(url(site), headers=h))) == 1203


def test_access_control(client, db, viewer):
    site, _ = viewer
    make_user(db, "outsider@example.com")
    assert client.get(url(site)).status_code == 401
    assert client.get(url(site), headers=login(client, "outsider@example.com")).status_code == 404


def test_export_is_audited_without_contents(client, db, viewer):
    site, h = viewer
    seed(db, site, message="secret words", email="p@example.com")
    client.get(url(site, "?q=secret"), headers=h)
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "feedback.export")).one()
    assert ev.details == {"rows": 1, "status": None, "search": True}
    assert "secret" not in ev.summary and "secret" not in str(ev.details)
    assert ev.actor_email == "v@example.com"

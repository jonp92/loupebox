import uuid

from sqlalchemy import select

from app.models import AuditEvent, Feedback, FeedbackStatus, Role
from tests.conftest import add_member, login, make_site, make_user


def seed(db, site, **kw) -> Feedback:
    item = Feedback(site_id=site.id, content_hash="h", ip_hash="i", **{"message": "hello", **kw})
    db.add(item)
    db.commit()
    return item


def world(db):
    """Two sites the user is on (editor on A, viewer on B) and one they are not on."""
    a, b, c = make_site(db, "Alpha"), make_site(db, "Beta"), make_site(db, "Gamma")
    me = make_user(db, "me@example.com")
    add_member(db, me, a, Role.editor)
    add_member(db, me, b, Role.viewer)
    return a, b, c, me


def inbox(client, h, qs=""):
    r = client.get(f"/inbox{qs}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_inbox_lists_only_the_callers_sites(client, db):
    a, b, c, _ = world(db)
    seed(db, a, message="in a")
    seed(db, b, message="in b")
    seed(db, c, message="in c")
    h = login(client, "me@example.com")
    page = inbox(client, h)
    assert {i["message"] for i in page["items"]} == {"in a", "in b"}
    assert page["total"] == 2
    by = {i["message"]: i for i in page["items"]}
    assert (by["in a"]["site_name"], by["in a"]["my_role"]) == ("Alpha", "editor")
    assert by["in b"]["my_role"] == "viewer"
    assert by["in a"]["metadata"] == {}


def test_inbox_newest_first_and_pages(client, db):
    a, b, _, _ = world(db)
    for n in range(3):
        seed(db, a if n % 2 else b, message=str(n))
    h = login(client, "me@example.com")
    page = inbox(client, h, "?limit=2")
    assert [i["message"] for i in page["items"]] == ["2", "1"] and page["total"] == 3
    assert [i["message"] for i in inbox(client, h, "?limit=2&offset=2")["items"]] == ["0"]


def test_superadmin_sees_every_site_as_admin(client, db):
    a, _, c, _ = world(db)
    seed(db, a, message="in a")
    seed(db, c, message="in c")
    make_user(db, "root@example.com", superadmin=True)
    page = inbox(client, login(client, "root@example.com"))
    assert {(i["message"], i["my_role"]) for i in page["items"]} == {("in a", "admin"), ("in c", "admin")}


def test_site_filter_and_unknown_site(client, db):
    a, b, c, _ = world(db)
    seed(db, a, message="in a")
    seed(db, b, message="in b")
    h = login(client, "me@example.com")
    assert [i["message"] for i in inbox(client, h, f"?site_id={a.id}")["items"]] == ["in a"]
    # A site the caller is not on is indistinguishable from one that does not exist.
    assert client.get(f"/inbox?site_id={c.id}", headers=h).status_code == 404
    assert client.get(f"/inbox?site_id={uuid.uuid4()}", headers=h).status_code == 404
    assert client.get(f"/inbox/counts?site_id={c.id}", headers=h).status_code == 404


def test_inbox_filters_like_the_site_list(client, db):
    a, b, _, me = world(db)
    seed(db, a, message="new one", rating=5)
    seed(db, b, message="read one", rating=5, status=FeedbackStatus.read)
    seed(db, a, message="spam one", status=FeedbackStatus.spam)
    seed(db, b, message="mine", assignee_id=me.id)
    h = login(client, "me@example.com")
    msgs = lambda qs: {i["message"] for i in inbox(client, h, qs)["items"]}
    assert msgs("") == {"new one", "read one", "mine"}  # spam is hidden by default
    assert msgs("?status=spam") == {"spam one"}
    assert msgs("?status=read") == {"read one"}
    assert msgs("?rating=5") == {"new one", "read one"}
    assert msgs("?q=one&status=new") == {"new one"}
    assert msgs(f"?assignee={me.id}") == {"mine"}
    assert msgs("?assignee=none") == {"new one", "read one"}


def test_no_sites_is_an_empty_inbox(client, db):
    make_user(db, "lonely@example.com")
    h = login(client, "lonely@example.com")
    assert inbox(client, h) == {"items": [], "total": 0, "total_capped": False}
    assert inbox(client, h, "/counts")["unread"] == 0


def test_counts(client, db):
    a, b, c, me = world(db)
    seed(db, a, assignee_id=me.id)
    seed(db, b, status=FeedbackStatus.read)
    seed(db, b, status=FeedbackStatus.spam)
    seed(db, c)
    counts = inbox(client, login(client, "me@example.com"), "/counts")
    assert (counts["mine"], counts["unassigned"], counts["unread"]) == (1, 1, 1)


def bulk(client, h, ids, **body):
    return client.post("/inbox/bulk", headers=h, json={"ids": [str(i.id) for i in ids], **body})


def test_bulk_status_skips_sites_without_editor_role(client, db):
    a, b, c, _ = world(db)
    ia, ib, ic = seed(db, a), seed(db, b), seed(db, c)
    r = bulk(client, login(client, "me@example.com"), [ia, ib, ic], action="set_status", status="archived")
    assert r.json() == {"affected": 1, "skipped": 2}
    for item in (ia, ib, ic):
        db.refresh(item)
    assert (ia.status, ib.status, ic.status) == (
        FeedbackStatus.archived,
        FeedbackStatus.new,
        FeedbackStatus.new,
    )


def test_bulk_assign_me_and_unassign_is_audited_without_text(client, db):
    a, _, _, me = world(db)
    item = seed(db, a, message="private words")
    h = login(client, "me@example.com")
    assert bulk(client, h, [item], action="assign_me").json() == {"affected": 1, "skipped": 0}
    db.refresh(item)
    assert item.assignee_id == me.id
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "feedback.bulk_assign")).one()
    assert event.details["ids"] == [str(item.id)] and "private words" not in str(event.details)
    assert bulk(client, h, [item], action="unassign").json()["affected"] == 1
    db.refresh(item)
    assert item.assignee_id is None


def test_superadmin_who_is_not_a_member_cannot_assign_to_self(client, db):
    a = make_site(db)
    item = seed(db, a)
    make_user(db, "root@example.com", superadmin=True)
    h = login(client, "root@example.com")
    assert bulk(client, h, [item], action="assign_me").json() == {"affected": 0, "skipped": 1}
    assert bulk(client, h, [item], action="set_status", status="read").json()["affected"] == 1


def test_bulk_validation(client, db):
    a, _, _, _ = world(db)
    item = seed(db, a)
    h = login(client, "me@example.com")
    assert bulk(client, h, [item], action="set_status").status_code == 422  # needs a status
    assert bulk(client, h, [item], action="assign_me", status="read").status_code == 422
    assert bulk(client, h, [item], action="delete").status_code == 422  # not offered here
    assert client.post("/inbox/bulk", headers=h, json={"ids": [], "action": "unassign"}).status_code == 422


def test_requires_login(client):
    assert client.get("/inbox").status_code == 401
    assert (
        client.post("/inbox/bulk", json={"ids": [str(uuid.uuid4())], "action": "unassign"}).status_code == 401
    )

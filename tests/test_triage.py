import uuid

import pytest
from sqlalchemy import select

from app.models import AuditEvent, FeedbackTag, Role, User
from tests.conftest import add_member, make_site, make_user
from tests.test_bulk_filters import as_role, bulk, listed, seed


def url(site, item, tail=""):
    return f"/sites/{site.id}/feedback/{item.id}{tail}"


def patch(client, site, item, h, **body):
    return client.patch(url(site, item), headers=h, json=body)


def audited(db, action):
    return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action)))


@pytest.fixture
def setup(client, db):
    site = make_site(db)
    h = as_role(client, db, site, Role.editor, "ed@example.com")
    return site, h, seed(db, site)


def user_id(db, email):
    return str(make_user(db, email).id)


def test_status_only_patch_still_works(client, db, setup):
    site, h, item = setup
    r = patch(client, site, item, h, status="read")
    assert r.status_code == 200 and r.json()["status"] == "read" and r.json()["tags"] == []


@pytest.mark.parametrize("body", [{}, {"status": None}, {"tags": None}, {"nope": 1}, {"tags": ["bad tag!"]}, {"tags": [str(n) for n in range(11)]}])
def test_bad_patch_rejected(client, setup, body):
    site, h, item = setup
    assert patch(client, site, item, h, **body).status_code == 422


def test_tags_are_normalised_and_replace(client, setup):
    site, h, item = setup
    r = patch(client, site, item, h, tags=["Needs Review", "needs-review", "bug"])
    assert r.json()["tags"] == ["bug", "needs-review"]
    assert patch(client, site, item, h, tags=[]).json()["tags"] == []


def test_assignee_must_be_editor_or_admin_of_the_site(client, db, setup):
    site, h, item = setup
    viewer, outsider = user_id(db, "v@example.com"), user_id(db, "o@example.com")
    add_member(db, db.get(User, uuid.UUID(viewer)), site, Role.viewer)
    for bad in (viewer, outsider, str(uuid.uuid4())):
        assert patch(client, site, item, h, assignee_id=bad).status_code == 422
    admin = _member(db, site, "adm@example.com", Role.admin)
    r = patch(client, site, item, h, assignee_id=admin)
    assert r.status_code == 200 and r.json()["assignee_id"] == admin
    assert patch(client, site, item, h, assignee_id=None).json()["assignee_id"] is None
    assert len(audited(db, "feedback.assign")) == 2


def _member(db, site, email, role):
    u = make_user(db, email)
    add_member(db, u, site, role)
    return str(u.id)


def test_viewer_cannot_triage_but_can_read(client, db, setup):
    site, _, item = setup
    h = as_role(client, db, site, Role.viewer, "view@example.com")
    assert patch(client, site, item, h, tags=["x"]).status_code == 403
    assert client.post(url(site, item, "/notes"), headers=h, json={"body": "hi"}).status_code == 403
    assert client.get(url(site, item, "/notes"), headers=h).status_code == 200
    assert client.get(f"/sites/{site.id}/feedback/tags", headers=h).status_code == 200


def test_filter_by_tag_and_assignee(client, db, setup):
    site, h, _ = setup
    a, b = seed(db, site, message="a"), seed(db, site, message="b")
    me = _member(db, site, "me@example.com", Role.editor)
    patch(client, site, a, h, tags=["bug"], assignee_id=me)
    patch(client, site, b, h, tags=["idea"])
    assert listed(client, site, h, "?tag=bug") == {"a"}
    assert listed(client, site, h, f"?assignee={me}") == {"a"}
    assert listed(client, site, h, "?assignee=none") == {"hello", "b"}
    assert client.get(f"/sites/{site.id}/feedback?tag=Bad Tag", headers=h).status_code == 422
    assert client.get(f"/sites/{site.id}/feedback?assignee=zzz", headers=h).status_code == 422
    tags = client.get(f"/sites/{site.id}/feedback/tags", headers=h).json()
    assert {t["tag"]: t["count"] for t in tags} == {"bug": 1, "idea": 1}
    assert [a["email"] for a in client.get(f"/sites/{site.id}/feedback/assignees", headers=h).json()] == ["ed@example.com", "me@example.com"]


def test_tags_do_not_leak_across_sites(client, db, setup):
    site, h, item = setup
    patch(client, site, item, h, tags=["secret"])
    other = make_site(db, "Other")
    oh = as_role(client, db, other, Role.editor, "oe@example.com")
    assert client.get(f"/sites/{other.id}/feedback/tags", headers=oh).json() == []
    assert client.patch(url(other, item), headers=oh, json={"tags": ["x"]}).status_code == 404


def test_bulk_assign_and_tags(client, db, setup):
    site, h, first = setup
    second, foreign = seed(db, site, message="2"), seed(db, make_site(db, "Other"))
    me = _member(db, site, "me@example.com", Role.editor)
    ids = [str(first.id), str(second.id), str(foreign.id)]
    r = bulk(client, site, h, ids=ids, action="assign", assignee_id=me)
    assert r.json() == {"affected": 2, "skipped": 1}
    r = bulk(client, site, h, ids=ids, action="add_tag", tag="Follow Up")
    assert r.json() == {"affected": 2, "skipped": 1}
    db.expire_all()
    assert second.tags == ["follow-up"] and str(second.assignee_id) == me and foreign.tags == []
    bulk(client, site, h, ids=ids, action="remove_tag", tag="follow-up")
    bulk(client, site, h, ids=ids, action="assign")  # unassigns
    db.expire_all()
    assert first.tags == [] and first.assignee_id is None
    actions = {e.action for e in db.scalars(select(AuditEvent))}
    assert {"feedback.bulk_assign", "feedback.add_tag", "feedback.remove_tag"} <= actions


@pytest.mark.parametrize("body", [
    {"action": "add_tag"}, {"action": "add_tag", "tag": "a", "status": "read"},
    {"action": "set_status", "status": "read", "tag": "a"}, {"action": "delete", "tag": "a"},
    {"action": "assign", "tag": "a"}, {"action": "add_tag", "tag": "bad!"},
])
def test_bulk_arguments_must_match_action(client, setup, body):
    site, h, item = setup
    assert bulk(client, site, h, ids=[str(item.id)], **body).status_code == 422


def test_bulk_assign_checks_assignee_and_tag_limit(client, db, setup):
    site, h, item = setup
    assert bulk(client, site, h, ids=[str(item.id)], action="assign", assignee_id=user_id(db, "o@example.com")).status_code == 422
    patch(client, site, item, h, tags=[f"t{n}" for n in range(10)])
    assert bulk(client, site, h, ids=[str(item.id)], action="add_tag", tag="one-more").status_code == 422


def test_notes_lifecycle_and_permissions(client, db, setup):
    site, h, item = setup
    r = client.post(url(site, item, "/notes"), headers=h, json={"body": "  looks like a dupe  "})
    assert r.status_code == 201 and r.json()["body"] == "looks like a dupe"
    note = r.json()["id"]
    assert client.post(url(site, item, "/notes"), headers=h, json={"body": "  "}).status_code == 422
    assert [n["body"] for n in client.get(url(site, item, "/notes"), headers=h).json()] == ["looks like a dupe"]
    # another editor cannot delete it, an admin can
    h2 = as_role(client, db, site, Role.editor, "ed2@example.com")
    assert client.delete(url(site, item, f"/notes/{note}"), headers=h2).status_code == 403
    h3 = as_role(client, db, site, Role.admin, "adm@example.com")
    assert client.delete(url(site, item, f"/notes/{note}"), headers=h3).status_code == 204
    assert client.delete(url(site, item, f"/notes/{note}"), headers=h3).status_code == 404
    ev = audited(db, "feedback.note_delete")[0]
    assert "looks like" not in str(ev.details) + ev.summary


def test_notes_are_not_in_the_feedback_payload_or_export(client, db, setup):
    site, h, item = setup
    client.post(url(site, item, "/notes"), headers=h, json={"body": "INTERNAL-ONLY"})
    assert "INTERNAL-ONLY" not in client.get(url(site, item), headers=h).text
    assert "INTERNAL-ONLY" not in client.get(f"/sites/{site.id}/feedback", headers=h).text
    assert "INTERNAL-ONLY" not in client.get(f"/sites/{site.id}/feedback/export.csv", headers=h).text


def test_notes_are_scoped_to_their_item_and_site(client, db, setup):
    site, h, item = setup
    other = seed(db, site, message="other")
    note = client.post(url(site, item, "/notes"), headers=h, json={"body": "x"}).json()["id"]
    assert client.delete(url(site, other, f"/notes/{note}"), headers=h).status_code == 404
    foreign_site = make_site(db, "Other")
    fh = as_role(client, db, foreign_site, Role.admin, "fa@example.com")
    assert client.get(url(foreign_site, item, "/notes"), headers=fh).status_code == 404


def test_removing_member_or_demoting_clears_assignments(client, db, setup):
    site, h, item = setup
    admin_h = as_role(client, db, site, Role.admin, "adm@example.com")
    me = _member(db, site, "me@example.com", Role.editor)
    patch(client, site, item, h, assignee_id=me)
    r = client.put(f"/sites/{site.id}/members", headers=admin_h, json={"email": "me@example.com", "role": "viewer"})
    assert r.status_code == 200
    db.expire_all()
    assert item.assignee_id is None
    patch(client, site, item, h, assignee_id=_member(db, site, "me2@example.com", Role.editor))
    assert client.delete(f"/sites/{site.id}/members/{_user_id_by(db, 'me2@example.com')}", headers=admin_h).status_code == 204
    db.expire_all()
    assert item.assignee_id is None


def _user_id_by(db, email):
    return db.scalar(select(User.id).where(User.email == email))


def test_deleting_feedback_removes_its_tags_and_notes(client, db, setup):
    site, h, item = setup
    patch(client, site, item, h, tags=["x"])
    client.post(url(site, item, "/notes"), headers=h, json={"body": "n"})
    admin_h = as_role(client, db, site, Role.admin, "adm@example.com")
    assert client.delete(url(site, item), headers=admin_h).status_code == 204
    assert db.scalar(select(FeedbackTag)) is None  # notes go via the database's cascade (not enforced on SQLite)


def test_export_has_tags_and_assignee(client, db, setup):
    site, h, item = setup
    me = _member(db, site, "me@example.com", Role.editor)
    patch(client, site, item, h, tags=["b", "a"], assignee_id=me)
    lines = client.get(f"/sites/{site.id}/feedback/export.csv", headers=h).content.decode("utf-8-sig").splitlines()
    assert lines[0].endswith(",tags,assignee") and lines[1].endswith(",a b,me@example.com")


def test_note_count_in_list_and_detail(client, db, setup):
    site, h, item = setup
    other = seed(db, site, message="other")
    for body in ("one", "two"):
        client.post(url(site, item, "/notes"), headers=h, json={"body": body})
    assert client.get(url(site, item), headers=h).json()["note_count"] == 2
    counts = {i["message"]: i["note_count"] for i in client.get(f"/sites/{site.id}/feedback", headers=h).json()["items"]}
    assert counts == {"hello": 2, "other": 0} and other


def test_quick_counts_exclude_spam_and_other_users(client, db, setup):
    site, h, item = setup
    me = client.get("/auth/me", headers=h).json()["id"]
    spam, theirs = seed(db, site, status="spam"), seed(db, site)
    patch(client, site, item, h, assignee_id=me)
    patch(client, site, theirs, h, assignee_id=_member(db, site, "o@example.com", Role.editor))
    patch(client, site, spam, h, assignee_id=me)
    assert client.get(f"/sites/{site.id}/feedback/counts", headers=h).json() == {"mine": 1, "unassigned": 0}


def test_dashboard_lists_my_open_assignments(client, db, setup):
    site, h, item = setup
    me = client.get("/auth/me", headers=h).json()["id"]
    done = seed(db, site, message="done")
    patch(client, site, item, h, assignee_id=me)
    patch(client, site, done, h, assignee_id=me, status="archived")
    r = client.get("/dashboard", headers=h).json()
    assert r["assigned_total"] == 1 and [i["id"] for i in r["assigned"]] == [str(item.id)]
    assert r["assigned"][0]["site_name"] == site.name


def test_assignee_search_is_limited_and_editor_only(client, db, setup):
    site, h, _ = setup
    for n in range(12):
        u = make_user(db, f"person{n:02d}@example.com")
        u.first_name, u.last_name = ("Zed" if n == 3 else "Pat"), f"N{n}"
        add_member(db, u, site, Role.editor)
    get = lambda qs: client.get(f"/sites/{site.id}/feedback/assignees{qs}", headers=h).json()
    assert len(get("")) == 8 and len(get("?limit=3")) == 3
    assert [a["email"] for a in get("?q=zed")] == ["person03@example.com"]  # matches the name, any case
    assert get("?q=person03")[0]["name"] == "Zed N3"
    assert get("?q=%25") == []  # a wildcard is just text
    assert client.get(f"/sites/{site.id}/feedback/assignees?limit=999", headers=h).status_code == 422
    viewer_h = as_role(client, db, site, Role.viewer, "view@example.com")
    assert client.get(f"/sites/{site.id}/feedback/assignees", headers=viewer_h).status_code == 403


def test_names_are_included_for_assignee_and_note_authors(client, db, setup):
    site, h, item = setup
    me = client.get("/auth/me", headers=h).json()
    patch(client, site, item, h, assignee_id=me["id"])
    got = client.get(url(site, item), headers=h).json()
    assert got["assignee_name"] == "ed@example.com"  # no name set: falls back to the email
    note = client.post(url(site, item, "/notes"), headers=h, json={"body": "x"}).json()
    assert note["author_name"] == "ed@example.com"
    assert client.get(url(site, item, "/notes"), headers=h).json()[0]["author_name"] == "ed@example.com"

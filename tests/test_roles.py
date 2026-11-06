from app.models import Feedback, Role
from tests.conftest import SITE_ORIGIN, add_member, login, make_site, make_user


def seed_feedback(db, site):
    fb = Feedback(site_id=site.id, message="hello", content_hash="h", ip_hash="i", meta={})
    db.add(fb)
    db.commit()
    return fb


def test_site_visibility_scoped_to_membership(client, db):
    a, b = make_site(db, "A"), make_site(db, "B")
    user = make_user(db, "u@example.com")
    add_member(db, user, a, Role.viewer)
    h = login(client, "u@example.com")
    assert [s["name"] for s in client.get("/sites", headers=h).json()] == ["A"]
    assert client.get(f"/sites/{a.id}", headers=h).status_code == 200
    assert client.get(f"/sites/{b.id}", headers=h).status_code == 404
    assert client.get(f"/sites/{b.id}/feedback", headers=h).status_code == 404


def test_role_matrix(client, db):
    site = make_site(db)
    fb = seed_feedback(db, site)
    for email, role in [("v@e.com", Role.viewer), ("e@e.com", Role.editor), ("a@e.com", Role.admin)]:
        add_member(db, make_user(db, email), site, role)
    v, e, a = (login(client, x) for x in ("v@e.com", "e@e.com", "a@e.com"))
    url = f"/sites/{site.id}/feedback/{fb.id}"

    assert client.get(f"/sites/{site.id}/feedback", headers=v).status_code == 200
    assert client.get(url, headers=v).json()["id"] == str(fb.id)
    assert client.patch(url, json={"status": "read"}, headers=v).status_code == 403
    assert client.patch(url, json={"status": "read"}, headers=e).status_code == 200
    assert client.delete(url, headers=e).status_code == 403
    assert client.patch(f"/sites/{site.id}", json={"name": "X"}, headers=e).status_code == 403
    assert client.get(f"/sites/{site.id}/members", headers=e).status_code == 403
    assert client.patch(f"/sites/{site.id}", json={"name": "X"}, headers=a).status_code == 200
    assert client.delete(url, headers=a).status_code == 204


def test_only_superadmin_creates_sites_and_users(client, db):
    make_user(db, "u@example.com")
    make_user(db, "root@example.com", superadmin=True)
    u, root = login(client, "u@example.com"), login(client, "root@example.com")
    assert client.post("/sites", json={"name": "N"}, headers=u).status_code == 403
    assert client.get("/users", headers=u).status_code == 403
    r = client.post("/sites", json={"name": "N", "allowed_origins": ["HTTPS://Example.com/"]}, headers=root)
    assert r.status_code == 201
    assert r.json()["allowed_origins"] == ["https://example.com"]
    assert r.json()["public_key"].startswith("pk_")


def test_origin_validation(client, db):
    make_user(db, "root@example.com", superadmin=True)
    root = login(client, "root@example.com")
    for bad in ["*", "example.com", "https://example.com/path", "javascript:alert(1)"]:
        r = client.post("/sites", json={"name": "N", "allowed_origins": [bad]}, headers=root)
        assert r.status_code == 422, bad


def test_rotate_key_invalidates_old(client, db):
    site = make_site(db)
    make_user(db, "root@example.com", superadmin=True)
    root = login(client, "root@example.com")
    new_key = client.post(f"/sites/{site.id}/rotate-key", headers=root).json()["public_key"]
    old = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}
    assert client.post("/feedback", json={"message": "x"}, headers=old).status_code == 403
    assert (
        client.post("/feedback", json={"message": "x"}, headers={**old, "X-API-Key": new_key}).status_code
        == 201
    )


def test_origin_change_takes_effect_for_cors(client, db):
    site = make_site(db, origins=[])
    make_user(db, "root@example.com", superadmin=True)
    root = login(client, "root@example.com")
    pre = {"Origin": "https://new.example.com", "Access-Control-Request-Method": "POST"}
    assert client.options("/feedback", headers=pre).status_code == 403
    client.patch(f"/sites/{site.id}", json={"allowed_origins": ["https://new.example.com"]}, headers=root)
    assert client.options("/feedback", headers=pre).status_code == 204


def test_membership_management(client, db):
    site = make_site(db)
    make_user(db, "root@example.com", superadmin=True)
    make_user(db, "u@example.com")
    root = login(client, "root@example.com")
    r = client.put(
        f"/sites/{site.id}/members", json={"email": "U@example.com", "role": "editor"}, headers=root
    )
    assert r.status_code == 200
    members = client.get(f"/sites/{site.id}/members", headers=root).json()
    assert [(m["email"], m["role"]) for m in members] == [("u@example.com", "editor")]
    assert client.delete(f"/sites/{site.id}/members/{members[0]['user_id']}", headers=root).status_code == 204


def test_spam_hidden_by_default_and_search(client, db):
    site = make_site(db)
    make_user(db, "root@example.com", superadmin=True)
    root = login(client, "root@example.com")
    db.add_all(
        [
            Feedback(
                site_id=site.id, message="50% off", content_hash="1", ip_hash="i", meta={}, status="spam"
            ),
            Feedback(site_id=site.id, message="great app", content_hash="2", ip_hash="i", meta={}),
        ]
    )
    db.commit()
    base = f"/sites/{site.id}/feedback"
    assert client.get(base, headers=root).json()["total"] == 1
    assert client.get(base, params={"status": "spam"}, headers=root).json()["total"] == 1
    assert client.get(base, params={"q": "great"}, headers=root).json()["total"] == 1
    assert client.get(base, params={"q": "%"}, headers=root).json()["total"] == 0


def test_user_search_for_site_admins(client, db):
    site, other_site = make_site(db), make_site(db, "Blog")
    admin = make_user(db, "boss@example.com")
    add_member(db, admin, site, Role.admin)
    add_member(db, admin, other_site, Role.viewer)
    viewer = make_user(db, "viewer@example.com")
    add_member(db, viewer, site, Role.viewer)
    for email in ("alice@example.com", "alicia@example.com"):
        add_member(db, make_user(db, email), other_site, Role.viewer)
    off = make_user(db, "alison@example.com")
    add_member(db, off, other_site, Role.viewer)
    off.is_active = False
    db.commit()
    h = login(client, "boss@example.com")
    url = f"/sites/{site.id}/user-search"

    found = client.get(url, params={"q": "ali"}, headers=h).json()
    assert [u["email"] for u in found] == ["alice@example.com", "alicia@example.com"]
    assert client.get(url, params={"q": "viewer"}, headers=h).json() == []  # already a member
    assert client.get(url, params={"q": "a"}, headers=h).status_code == 422  # too short
    assert client.get(url, params={"q": "%%"}, headers=h).json() == []  # wildcards escaped

    v = login(client, "viewer@example.com")
    assert client.get(url, params={"q": "ali"}, headers=v).status_code == 403


def test_site_admins_find_strangers_only_by_full_email(client, db):
    site = make_site(db)
    add_member(db, make_user(db, "boss@example.com"), site, Role.admin)
    make_user(db, "stranger@example.com")
    make_user(db, "root@example.com", superadmin=True)
    url = f"/sites/{site.id}/user-search"

    def emails(h, q):
        return [u["email"] for u in client.get(url, params={"q": q}, headers=h).json()]

    boss = login(client, "boss@example.com")
    assert emails(boss, "strang") == []
    assert emails(boss, "example.com") == []  # nobody shares a site with boss
    assert emails(boss, " Stranger@Example.com ") == ["stranger@example.com"]

    root = login(client, "root@example.com")
    assert emails(root, "strang") == ["stranger@example.com"]


def test_superadmin_can_promote_and_demote_others_but_not_self(client, db):
    root = make_user(db, "root@e.com")
    root.is_superadmin = True
    other = make_user(db, "o@e.com")
    db.commit()
    h = login(client, "root@e.com")

    r = client.patch(f"/users/{other.id}", json={"is_superadmin": True}, headers=h)
    assert r.status_code == 200 and r.json()["is_superadmin"] is True
    assert (
        client.patch(f"/users/{other.id}", json={"is_superadmin": False}, headers=h).json()["is_superadmin"]
        is False
    )
    assert client.patch(f"/users/{root.id}", json={"is_superadmin": False}, headers=h).status_code == 400

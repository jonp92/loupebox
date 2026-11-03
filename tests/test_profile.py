from app.core.config import settings
from app.models import Role
from tests.conftest import add_member, login, make_site, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def put_avatar(client, headers, raw=PNG, content_type="image/png"):
    return client.put("/auth/me/avatar", content=raw, headers={**headers, "Content-Type": content_type})


def test_avatar_upload_serve_and_delete(client, db):
    user = make_user(db, "u@example.com")
    h = login(client, "u@example.com")
    assert client.get("/auth/me", headers=h).json()["avatar_url"] is None
    assert client.get(f"/avatars/{user.id}").status_code == 404

    r = put_avatar(client, h)
    assert r.status_code == 200
    url = r.json()["avatar_url"]
    assert url.startswith(f"{settings.api_prefix}/avatars/{user.id}?v=")
    assert "avatar" not in r.json()  # no inline image data in JSON

    img = client.get(url.removeprefix(settings.api_prefix))  # no auth needed so <img src> works
    assert img.status_code == 200 and img.content == PNG
    assert img.headers["content-type"] == "image/png"
    assert "immutable" in img.headers["cache-control"]
    assert img.headers["x-content-type-options"] == "nosniff"

    assert client.delete("/auth/me/avatar", headers=h).json()["avatar_url"] is None
    assert client.get(f"/avatars/{user.id}").status_code == 404


def test_avatar_url_changes_with_new_upload(client, db):
    make_user(db, "u@example.com")
    h = login(client, "u@example.com")
    first = put_avatar(client, h).json()["avatar_url"]
    import time

    time.sleep(1.1)
    second = put_avatar(client, h, PNG + b"\x01").json()["avatar_url"]
    assert first != second


def test_avatar_requires_auth(client):
    assert client.put("/auth/me/avatar", content=PNG, headers={"Content-Type": "image/png"}).status_code == 401
    assert client.delete("/auth/me/avatar").status_code == 401


def test_avatar_rejections(client, db):
    make_user(db, "u@example.com")
    h = login(client, "u@example.com")
    assert put_avatar(client, h, b"<svg onload=alert(1)/>", "image/svg+xml").status_code == 415
    assert put_avatar(client, h, b"<html>", "text/html").status_code == 415
    assert put_avatar(client, h, b"not a png at all", "image/png").status_code == 422
    assert put_avatar(client, h, b"", "image/png").status_code == 422
    # real JPEG bytes declared as PNG
    assert put_avatar(client, h, b"\xff\xd8\xff" + b"\0" * 8, "image/png").status_code == 422
    assert put_avatar(client, h, b"\xff\xd8\xff" + b"\0" * 8, "image/jpeg").status_code == 200


def test_avatar_size_cap(client, db):
    make_user(db, "u@example.com")
    h = login(client, "u@example.com")
    ok = PNG + b"\x00" * (settings.avatar_max_bytes - len(PNG))
    assert put_avatar(client, h, ok).status_code == 200
    # over the avatar cap but within the raised body limit: app-level 413
    assert put_avatar(client, h, ok + b"\x00" * 10).status_code == 413
    # far over: rejected by the body limit middleware before reading
    assert put_avatar(client, h, ok + b"\x00" * 5000).status_code == 413


def test_body_limit_still_tight_elsewhere(client, db):
    make_user(db, "u@example.com")
    h = login(client, "u@example.com")
    r = client.post("/auth/me/password", content=b"x" * (settings.max_body_bytes + 1), headers=h)
    assert r.status_code == 413


def test_lists_expose_avatar_url_not_data(client, db):
    site = make_site(db)
    admin = make_user(db, "boss@example.com")
    add_member(db, admin, site, Role.admin)
    make_user(db, "root@example.com", superadmin=True)
    h = login(client, "boss@example.com")
    put_avatar(client, h)
    members = client.get(f"/sites/{site.id}/members", headers=h).json()
    assert members[0]["avatar_url"].startswith(f"{settings.api_prefix}/avatars/") and "avatar" not in members[0]
    rh = login(client, "root@example.com")
    users = client.get("/users", headers=rh).json()
    assert {u["email"]: bool(u["avatar_url"]) for u in users} == {"boss@example.com": True, "root@example.com": False}


def test_user_cannot_change_own_name_or_email(client, db):
    u = make_user(db, "u@example.com")
    h = login(client, "u@example.com")
    assert client.patch(f"/users/{u.id}", json={"first_name": "X"}, headers=h).status_code == 403
    assert client.patch("/auth/me", json={"email": "evil@example.com"}, headers=h).status_code == 405


def test_change_password(client, db):
    make_user(db, "u@example.com")
    h = login(client, "u@example.com")

    wrong = client.post("/auth/me/password", json={"current_password": "nope-nope-nope", "new_password": "brand-new-password"}, headers=h)
    assert wrong.status_code == 400
    same = client.post("/auth/me/password", json={"current_password": "correct-horse-battery", "new_password": "correct-horse-battery"}, headers=h)
    assert same.status_code == 400
    short = client.post("/auth/me/password", json={"current_password": "correct-horse-battery", "new_password": "short"}, headers=h)
    assert short.status_code == 422

    old_refresh = client.cookies.get("refresh_token")
    ok = client.post("/auth/me/password", json={"current_password": "correct-horse-battery", "new_password": "brand-new-password"}, headers=h)
    assert ok.status_code == 200 and ok.json()["access_token"]
    # this session keeps working on its fresh refresh token; old one is dead
    assert client.cookies.get("refresh_token") != old_refresh
    assert client.post("/auth/refresh").status_code == 200

    client.cookies.clear()
    bad = client.post("/auth/login", json={"email": "u@example.com", "password": "correct-horse-battery"})
    assert bad.status_code == 401
    assert client.post("/auth/login", json={"email": "u@example.com", "password": "brand-new-password"}).status_code == 200


def test_superadmin_edits_name_and_email(client, db):
    root = make_user(db, "root@example.com", superadmin=True)
    u = make_user(db, "u@example.com")
    make_user(db, "taken@example.com")
    h = login(client, "root@example.com")

    r = client.patch(f"/users/{u.id}", json={"first_name": " Ada ", "last_name": "Lovelace", "email": "ADA@Example.com"}, headers=h)
    assert r.status_code == 200
    assert (r.json()["first_name"], r.json()["last_name"], r.json()["email"]) == ("Ada", "Lovelace", "ada@example.com")
    assert client.patch(f"/users/{u.id}", json={"email": "taken@example.com"}, headers=h).status_code == 409
    assert client.patch(f"/users/{u.id}", json={"first_name": ""}, headers=h).status_code == 422
    assert client.patch(f"/users/{root.id}", json={"first_name": "Root"}, headers=h).status_code == 200


def test_create_user_requires_names(client, db):
    make_user(db, "root@example.com", superadmin=True)
    h = login(client, "root@example.com")
    body = {"email": "n@example.com", "password": "long-enough-password"}
    assert client.post("/users", json=body, headers=h).status_code == 422
    r = client.post("/users", json={**body, "first_name": "New", "last_name": "Person"}, headers=h)
    assert r.status_code == 201 and r.json()["first_name"] == "New"


def test_user_search_matches_names_and_returns_profile(client, db):
    site = make_site(db)
    admin = make_user(db, "boss@example.com")
    add_member(db, admin, site, Role.admin)
    u = make_user(db, "x@example.com")
    u.first_name, u.last_name = "Grace", "Hopper"
    db.commit()
    h = login(client, "boss@example.com")
    found = client.get(f"/sites/{site.id}/user-search", params={"q": "hopp"}, headers=h).json()
    assert [(f["email"], f["first_name"]) for f in found] == [("x@example.com", "Grace")]


def test_superadmin_can_set_and_clear_another_users_avatar(client, db):
    root = make_user(db, "root@example.com", superadmin=True)
    other = make_user(db, "o@example.com")
    make_user(db, "plain@example.com")
    admin, plain = login(client, "root@example.com"), login(client, "plain@example.com")
    url = f"/users/{other.id}/avatar"

    r = client.put(url, content=PNG, headers={**admin, "Content-Type": "image/png"})
    assert r.status_code == 200 and r.json()["avatar_url"].startswith(f"{settings.api_prefix}/avatars/{other.id}?v=")
    assert client.get(f"/avatars/{other.id}").content == PNG
    assert client.put(url, content=b"nope", headers={**admin, "Content-Type": "image/png"}).status_code == 422

    assert client.delete(url, headers=admin).json()["avatar_url"] is None
    assert client.get(f"/avatars/{other.id}").status_code == 404

    assert client.put(url, content=PNG, headers={**plain, "Content-Type": "image/png"}).status_code == 403
    assert client.delete(url, headers=plain).status_code == 403
    assert client.delete(f"/users/{root.id.__class__(int=0)}/avatar", headers=admin).status_code == 404

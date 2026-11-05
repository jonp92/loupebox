from sqlalchemy import select

from app.core.config import settings
from app.models import RefreshToken
from tests.conftest import login, make_user


def test_login_and_me(client, db):
    make_user(db, "a@example.com")
    h = login(client, "A@Example.com")
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 200 and r.json()["email"] == "a@example.com"


def test_bad_credentials_same_error(client, db):
    make_user(db, "a@example.com")
    r1 = client.post("/auth/login", json={"email": "a@example.com", "password": "wrong-password-1"})
    r2 = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"})
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()


def test_requires_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_login_brute_force_limited(client, db):
    make_user(db, "a@example.com")
    body = {"email": "a@example.com", "password": "wrong-password-1"}
    codes = [
        client.post("/auth/login", json=body).status_code for _ in range(settings.login_account_limit + 1)
    ]
    assert codes[-1] == 429
    # Correct password is also blocked while locked out.
    assert client.post("/auth/login", json={**body, "password": "correct-horse-battery"}).status_code == 429


def attempt_login(client, ip, email="a@example.com", password="wrong-password-1") -> int:
    """One sign-in from `ip` (needs TRUST_PROXY). Returns the status code."""
    body = {"email": email, "password": password}
    return client.post("/auth/login", json=body, headers={"X-Forwarded-For": ip}).status_code


def test_failures_from_many_ips_lock_the_account(client, db, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)
    make_user(db, "a@example.com")
    make_user(db, "b@example.com")
    codes = [attempt_login(client, f"10.0.0.{i}") for i in range(settings.login_failure_limit)]
    assert set(codes) == {401}
    # Refused from a fresh IP too, even with the right password; other accounts are unaffected.
    assert attempt_login(client, "10.0.1.1", password="correct-horse-battery") == 429
    assert attempt_login(client, "10.0.1.2", "b@example.com", "correct-horse-battery") == 200


def test_unknown_emails_lock_the_same_way(client, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)
    n = settings.login_failure_limit + 1
    codes = [attempt_login(client, f"10.0.0.{i}", "nobody@example.com") for i in range(n)]
    assert codes[-1] == 429


def test_a_successful_sign_in_clears_failures(client, db, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)
    make_user(db, "a@example.com")
    for i in range(settings.login_failure_limit - 1):
        attempt_login(client, f"10.0.0.{i}")
    assert attempt_login(client, "10.0.1.1", password="correct-horse-battery") == 200
    codes = [attempt_login(client, f"10.0.2.{i}") for i in range(settings.login_failure_limit)]
    assert set(codes) == {401}


def test_refresh_rotates_and_detects_replay(client, db):
    make_user(db, "a@example.com")
    client.post("/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery"})
    old = client.cookies.get("refresh_token")
    assert client.post("/auth/refresh").status_code == 200
    new = client.cookies.get("refresh_token")
    assert new and new != old

    # Replaying the rotated token fails and revokes the whole family.
    client.cookies.set("refresh_token", old, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 401
    client.cookies.set("refresh_token", new, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 401
    assert all(t.revoked_at for t in db.scalars(select(RefreshToken)))


def test_logout_revokes(client, db):
    make_user(db, "a@example.com")
    client.post("/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery"})
    token = client.cookies.get("refresh_token")
    assert client.post("/auth/logout").status_code == 204
    client.cookies.set("refresh_token", token, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 401


def test_disabled_user_locked_out(client, db):
    user = make_user(db, "a@example.com")
    h = login(client, "a@example.com")
    user.is_active = False
    db.commit()
    assert client.get("/auth/me", headers=h).status_code == 401


def test_admin_cors_only_for_admin_origins(client):
    ok = client.options(
        "/auth/login", headers={"Origin": "http://admin.test", "Access-Control-Request-Method": "POST"}
    )
    assert ok.status_code == 204
    assert ok.headers["access-control-allow-credentials"] == "true"
    bad = client.options(
        "/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert bad.status_code == 403

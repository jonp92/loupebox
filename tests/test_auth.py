from datetime import timedelta

from sqlalchemy import select

from app.core.config import settings
from app.models import AuditEvent, RefreshToken
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


def _rotate(client, db):
    """Sign in, refresh once; returns (rotated cookie, current cookie)."""
    make_user(db, "a@example.com")
    client.post("/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery"})
    old = client.cookies.get("refresh_token")
    assert client.post("/auth/refresh").status_code == 200
    return old, client.cookies.get("refresh_token")


def test_just_rotated_token_is_accepted_in_the_grace_window(client, db):
    old, new = _rotate(client, db)
    client.cookies.set("refresh_token", old, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 200  # a racing refresh, not theft
    client.cookies.set("refresh_token", new, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 200  # the other session survived
    assert not db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.session_replay"))


def test_refresh_rotates_and_a_stale_replay_signs_everyone_out_and_is_audited(client, db):
    old, new = _rotate(client, db)
    assert new and new != old
    for t in db.scalars(select(RefreshToken)):
        t.rotated_at = t.rotated_at and t.rotated_at - timedelta(seconds=settings.refresh_grace_seconds + 1)
    db.commit()
    client.cookies.set("refresh_token", old, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 401
    client.cookies.set("refresh_token", new, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 401
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.session_replay"))
    assert event and event.details["seconds_since_rotation"] > settings.refresh_grace_seconds
    db.expire_all()
    assert all(t.revoked_at for t in db.scalars(select(RefreshToken)))


def test_password_change_ends_the_grace_window(client, db):
    old, _new = _rotate(client, db)
    h = {"Authorization": "Bearer " + client.post("/auth/refresh").json()["access_token"]}
    r = client.post(
        "/auth/me/password",
        json={"current_password": "correct-horse-battery", "new_password": "another-long-password-1"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    client.cookies.set("refresh_token", old, path=settings.cookie_path)
    assert client.post("/auth/refresh").status_code == 401  # revoked on purpose, not rotated


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

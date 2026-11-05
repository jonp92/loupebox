from sqlalchemy import select

from app.core import totp
from app.core.config import settings
from app.core.security import create_access_token, create_mfa_token
from app.models import AuditEvent, RecoveryCode, RefreshToken, User
from tests.conftest import login, make_user

PW = "correct-horse-battery"


def _enroll(client, db, email="a@example.com") -> tuple[dict, str, list[str]]:
    make_user(db, email)
    h = login(client, email)
    secret = client.post("/auth/me/totp/setup", headers=h).json()["secret"]
    r = client.post("/auth/me/totp/enable", headers=h, json={"code": totp._code(secret, totp.current_step())})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, secret, r.json()["recovery_codes"]


def _next_code(secret: str) -> str:
    """A valid code for a later step than any used so far (the replay guard refuses reuse)."""
    return totp._code(secret, totp.current_step() + 1)


def test_rfc6238_vectors():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
    # RFC 6238 appendix B, truncated to 6 digits.
    assert totp._code(secret, 59 // 30) == "287082"
    assert totp._code(secret, 1111111109 // 30) == "081804"
    assert totp.verify(secret, "287082", now=59) == 1
    assert totp.verify(secret, "287082", now=59 + 30) == 1  # previous step still accepted
    assert totp.verify(secret, "287082", now=59 + 90) is None
    assert totp.verify(secret, "287082", last_step=1, now=59) is None
    assert totp.verify(secret, "28708", now=59) is None
    assert totp.verify(secret, "abcdef", now=59) is None


def test_secret_encrypted_at_rest(client, db):
    _h, secret, _ = _enroll(client, db)
    stored = db.scalar(select(User.totp_secret))
    assert stored and secret not in stored
    assert totp.decrypt_secret(stored) == secret


def test_setup_is_inert_until_confirmed(client, db):
    make_user(db, "a@example.com")
    h = login(client, "a@example.com")
    body = client.post("/auth/me/totp/setup", headers=h).json()
    assert body["uri"].startswith("otpauth://totp/") and body["secret"] in body["uri"]
    assert client.get("/auth/me", headers=h).json()["totp_enabled"] is False
    # Login still works with the password alone.
    assert (
        "access_token" in client.post("/auth/login", json={"email": "a@example.com", "password": PW}).json()
    )
    bad = client.post("/auth/me/totp/enable", headers=h, json={"code": "000000"})
    assert bad.status_code == 400


def test_login_requires_code_when_enabled(client, db):
    h, secret, _ = _enroll(client, db)
    assert client.get("/auth/me", headers=h).json()["totp_enabled"] is True

    client.cookies.clear()
    r = client.post("/auth/login", json={"email": "a@example.com", "password": PW})
    assert r.status_code == 200
    assert r.json()["mfa_required"] is True and "access_token" not in r.json()
    assert "refresh_token" not in client.cookies  # no session before the second step

    mfa = r.json()["mfa_token"]
    assert client.post("/auth/login/totp", json={"mfa_token": mfa, "code": "000000"}).status_code == 401
    ok = client.post("/auth/login/totp", json={"mfa_token": mfa, "code": _next_code(secret)})
    assert ok.status_code == 200 and "refresh_token" in client.cookies
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"})
    assert me.status_code == 200


def test_code_cannot_be_replayed(client, db):
    _h, secret, _ = _enroll(client, db)
    code = _next_code(secret)
    mfa = create_mfa_token(db.scalar(select(User.id)))
    assert client.post("/auth/login/totp", json={"mfa_token": mfa, "code": code}).status_code == 200
    assert client.post("/auth/login/totp", json={"mfa_token": mfa, "code": code}).status_code == 401
    # The code used at enrollment is also dead.
    used = totp._code(secret, totp.current_step())
    assert client.post("/auth/login/totp", json={"mfa_token": mfa, "code": used}).status_code == 401


def test_mfa_token_is_not_an_access_token_and_vice_versa(client, db):
    _h, secret, _ = _enroll(client, db)
    uid = db.scalar(select(User.id))
    mfa = create_mfa_token(uid)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {mfa}"}).status_code == 401
    r = client.post(
        "/auth/login/totp", json={"mfa_token": create_access_token(uid), "code": _next_code(secret)}
    )
    assert r.status_code == 401
    r = client.post("/auth/login/totp", json={"mfa_token": "junk", "code": _next_code(secret)})
    assert r.status_code == 401


def test_expired_mfa_token(client, db, monkeypatch):
    _h, secret, _ = _enroll(client, db)
    monkeypatch.setattr(settings, "mfa_token_minutes", -1)
    mfa = create_mfa_token(db.scalar(select(User.id)))
    r = client.post("/auth/login/totp", json={"mfa_token": mfa, "code": _next_code(secret)})
    assert r.status_code == 401


def test_recovery_code_is_single_use_and_audited(client, db):
    _h, _secret, codes = _enroll(client, db)
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    assert db.scalar(select(RecoveryCode.code_hash)) not in codes  # only hashes are stored
    mfa = create_mfa_token(db.scalar(select(User.id)))
    ok = client.post("/auth/login/totp", json={"mfa_token": mfa, "code": codes[0].upper()})
    assert ok.status_code == 200
    again = client.post("/auth/login/totp", json={"mfa_token": mfa, "code": codes[0]})
    assert again.status_code == 401
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.recovery_code_used")).one()
    assert ev.details == {"remaining": totp.RECOVERY_CODE_COUNT - 1}
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).json()
    assert me["recovery_codes_left"] == totp.RECOVERY_CODE_COUNT - 1


def test_attempts_are_rate_limited(client, db):
    _h, secret, _ = _enroll(client, db)
    mfa = create_mfa_token(db.scalar(select(User.id)))
    codes = [
        client.post("/auth/login/totp", json={"mfa_token": mfa, "code": "000000"}).status_code
        for _ in range(settings.login_account_limit + 1)
    ]
    assert codes[-1] == 429
    # Even a correct code is refused while locked out.
    assert (
        client.post("/auth/login/totp", json={"mfa_token": mfa, "code": _next_code(secret)}).status_code
        == 429
    )


def test_enable_signs_out_other_sessions(client, db):
    make_user(db, "a@example.com")
    other = login(client, "a@example.com")  # a second session
    secret = client.post("/auth/me/totp/setup", headers=other).json()["secret"]
    client.post("/auth/login", json={"email": "a@example.com", "password": PW})
    client.post("/auth/me/totp/enable", headers=other, json={"code": totp._code(secret, totp.current_step())})
    rows = db.scalars(select(RefreshToken)).all()
    assert sum(1 for r in rows if r.revoked_at is None) == 1  # only the session that enabled it
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.totp_enable")).one()
    assert event.actor_email == "a@example.com"


def test_disable_needs_password_and_code(client, db):
    h, secret, codes = _enroll(client, db)
    url = "/auth/me/totp/disable"
    assert (
        client.post(
            url, headers=h, json={"password": "wrong-password-1", "code": _next_code(secret)}
        ).status_code
        == 400
    )
    assert client.post(url, headers=h, json={"password": PW, "code": "000000"}).status_code == 400
    assert client.get("/auth/me", headers=h).json()["totp_enabled"] is True

    r = client.post(url, headers=h, json={"password": PW, "code": codes[0]})  # a recovery code works too
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get("/auth/me", headers=h).json()
    assert me["totp_enabled"] is False and me["recovery_codes_left"] == 0
    assert db.scalars(select(RecoveryCode)).all() == []
    assert (
        "access_token" in client.post("/auth/login", json={"email": "a@example.com", "password": PW}).json()
    )
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.totp_disable")).one()


def test_regenerate_recovery_codes(client, db):
    h, secret, codes = _enroll(client, db)
    url = "/auth/me/totp/recovery-codes"
    assert (
        client.post(
            url, headers=h, json={"password": "wrong-password-1", "code": _next_code(secret)}
        ).status_code
        == 400
    )
    r = client.post(url, headers=h, json={"password": PW, "code": _next_code(secret)})
    assert r.status_code == 200
    new = r.json()["recovery_codes"]
    assert len(new) == totp.RECOVERY_CODE_COUNT and not set(new) & set(codes)
    mfa = create_mfa_token(db.scalar(select(User.id)))
    assert client.post("/auth/login/totp", json={"mfa_token": mfa, "code": codes[1]}).status_code == 401
    assert client.post("/auth/login/totp", json={"mfa_token": mfa, "code": new[1]}).status_code == 200


def test_setup_refused_once_enabled(client, db):
    h, _, _ = _enroll(client, db)
    assert client.post("/auth/me/totp/setup", headers=h).status_code == 400


def test_works_for_any_role_not_only_superadmins(client, db):
    _h, _secret, _ = _enroll(client, db, "plain@example.com")
    assert not db.scalar(select(User.is_superadmin))
    r = client.post("/auth/login", json={"email": "plain@example.com", "password": PW})
    assert r.json()["mfa_required"] is True


def test_superadmin_can_reset_totp(client, db):
    _, _secret, _ = _enroll(client, db, "user@example.com")
    victim = db.scalar(select(User.id).where(User.email == "user@example.com"))
    make_user(db, "root@example.com", superadmin=True)
    root = login(client, "root@example.com")

    users = {u["email"]: u for u in client.get("/users", headers=root).json()}
    assert (
        users["user@example.com"]["totp_enabled"] is True
        and users["root@example.com"]["totp_enabled"] is False
    )

    assert client.delete(f"/users/{victim}/totp", headers=root).json()["totp_enabled"] is False
    assert client.delete(f"/users/{victim}/totp", headers=root).status_code == 400  # already off
    assert all(r.revoked_at for r in db.scalars(select(RefreshToken).where(RefreshToken.user_id == victim)))
    assert (
        "access_token"
        in client.post("/auth/login", json={"email": "user@example.com", "password": PW}).json()
    )
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "user.totp_reset")).one()


def test_reset_is_superadmin_only(client, db):
    h, _, _ = _enroll(client, db, "user@example.com")
    uid = db.scalar(select(User.id))
    assert client.delete(f"/users/{uid}/totp", headers=h).status_code == 403
    assert client.get("/auth/me", headers=h).json()["totp_enabled"] is True


def test_disabled_user_cannot_finish_login(client, db):
    _h, secret, _ = _enroll(client, db)
    user = db.scalar(select(User))
    mfa = create_mfa_token(user.id)
    user.is_active = False
    db.commit()
    assert (
        client.post("/auth/login/totp", json={"mfa_token": mfa, "code": _next_code(secret)}).status_code
        == 401
    )


def test_login_lockout_does_not_block_managing_totp(client, db):
    h, _secret, codes = _enroll(client, db)
    mfa = create_mfa_token(db.scalar(select(User.id)))
    for _ in range(settings.login_account_limit + 1):
        client.post("/auth/login/totp", json={"mfa_token": mfa, "code": "000000"})
    r = client.post("/auth/me/totp/recovery-codes", headers=h, json={"password": PW, "code": codes[0]})
    assert r.status_code == 200

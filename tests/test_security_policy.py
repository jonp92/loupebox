"""System security policy: minimum password length and required two-factor authentication."""

import pytest
from sqlalchemy import select, update

from app.core import totp
from app.core.config import settings
from app.models import User
from tests.conftest import login, make_user
from tests.test_totp import PW, _enroll

NEW = {"first_name": "N", "last_name": "U", "email": "new@example.com", "is_superadmin": False}


@pytest.fixture
def root(client, db):
    make_user(db, "root@example.com", superadmin=True)
    return login(client, "root@example.com")


def test_minimum_password_length_applies_to_every_way_of_setting_one(client, db, root, monkeypatch):
    monkeypatch.setattr(settings, "password_min_length", 14)
    short = "a" * 13
    refused = client.post("/users", headers=root, json={**NEW, "password": short})
    assert refused.status_code == 422 and "at least 14" in refused.json()["detail"]
    assert client.post("/users", headers=root, json={**NEW, "password": "a" * 14}).status_code == 201

    user = make_user(db, "b@example.com")
    assert client.patch(f"/users/{user.id}", headers=root, json={"password": short}).status_code == 422
    change = {"current_password": PW, "new_password": short}
    assert (
        client.post("/auth/me/password", headers=login(client, "b@example.com"), json=change).status_code
        == 422
    )
    change["new_password"] = "b" * 14
    assert (
        client.post("/auth/me/password", headers=login(client, "b@example.com"), json=change).status_code
        == 200
    )


def test_minimum_can_be_lowered_and_is_public(client, root):
    assert client.get("/auth/features").json()["password_min_length"] == 12
    r = client.patch("/settings", headers=root, json={"changes": {"password_min_length": 8}})
    assert r.status_code == 200, r.text
    assert client.get("/auth/features").json()["password_min_length"] == 8
    bad = client.patch("/settings", headers=root, json={"changes": {"password_min_length": 7}})
    assert bad.status_code == 422


def test_without_2fa_only_enrollment_is_reachable(client, db, monkeypatch):
    make_user(db, "a@example.com")
    h = login(client, "a@example.com")
    assert client.get("/sites", headers=h).status_code == 200
    monkeypatch.setattr(settings, "require_totp", True)

    assert client.get("/auth/me", headers=h).json()["totp_required"] is True
    assert client.get("/sites", headers=h).status_code == 403
    assert client.put("/auth/me/avatar", headers=h, content=b"x").status_code == 403

    secret = client.post("/auth/me/totp/setup", headers=h).json()["secret"]
    enable = {"password": PW, "code": totp._code(secret, totp.current_step())}
    r = client.post("/auth/me/totp/enable", headers=h, json=enable)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/sites", headers=h).status_code == 200
    assert client.get("/auth/me", headers=h).json()["totp_required"] is False


def test_2fa_cannot_be_turned_off_while_required(client, db, monkeypatch):
    h, secret, _ = _enroll(client, db)
    monkeypatch.setattr(settings, "require_totp", True)
    code = totp._code(secret, totp.current_step() + 1)
    r = client.post("/auth/me/totp/disable", headers=h, json={"password": PW, "code": code})
    assert r.status_code == 400 and "required" in r.json()["detail"]


def test_reset_by_an_admin_sends_the_user_back_to_enrollment(client, db, root, monkeypatch):
    _enroll(client, db, "a@example.com")
    user = db.scalar(select(User).where(User.email == "a@example.com"))
    assert client.delete(f"/users/{user.id}/totp", headers=root).status_code in (200, 204)
    monkeypatch.setattr(settings, "require_totp", True)
    assert client.get("/sites", headers=login(client, "a@example.com")).status_code == 403


def test_requiring_2fa_needs_the_superadmin_to_have_it(client, db, root):
    r = client.patch("/settings", headers=root, json={"changes": {"require_totp": True}})
    assert r.status_code == 422 and "your own 2FA" in r.text
    assert settings.require_totp is False

    h, _secret, _ = _enroll(client, db, "owner@example.com")
    db.execute(update(User).where(User.email == "owner@example.com").values(is_superadmin=True))
    db.commit()
    r = client.patch("/settings", headers=h, json={"changes": {"require_totp": True}})
    assert r.status_code == 200, r.text
    assert settings.require_totp is True


def test_cli_can_drop_the_requirement(client, db, root, monkeypatch):
    from app.core import runtime_settings
    from app.models import AppSetting
    from scripts import reset_totp

    h, _secret, _ = _enroll(client, db, "owner@example.com")
    db.execute(update(User).where(User.email == "owner@example.com").values(is_superadmin=True))
    db.commit()
    assert client.patch("/settings", headers=h, json={"changes": {"require_totp": True}}).status_code == 200

    monkeypatch.setattr("sys.argv", ["reset_totp", "--stop-requiring"])
    reset_totp.main()
    assert db.scalar(select(AppSetting).where(AppSetting.key == "require_totp")) is None
    runtime_settings.load(db)
    assert settings.require_totp is False

    monkeypatch.setattr("sys.argv", ["reset_totp", "owner@example.com"])
    reset_totp.main()
    db.expire_all()
    assert db.scalar(select(User.totp_enabled_at).where(User.email == "owner@example.com")) is None

import pytest
from sqlalchemy import select

from app.core import runtime_settings
from app.core.config import settings
from app.db.session import get_sessionmaker
from app.models import AppSetting, AuditEvent, Role
from tests.conftest import add_member, login, make_site, make_user


@pytest.fixture
def h(client, db):
    make_user(db, "root@example.com", superadmin=True)
    return login(client, "root@example.com")


def by_key(items):
    return {s["key"]: s for s in items}


def patch(client, h, **changes):
    return client.patch("/settings", json={"changes": changes}, headers=h)


def test_lists_editable_and_read_only_settings(client, h):
    items = by_key(client.get("/settings", headers=h).json())
    cap = items["notify_hourly_cap"]
    assert cap["editable"] and cap["type"] == "integer" and cap["value"] == settings.notify_hourly_cap
    assert cap["source"] == "default" and cap["default"] == 5
    assert items["smtp_security"]["choices"] == ["starttls", "ssl", "none"]
    assert not items["trust_proxy"]["editable"]
    assert "jwt_secret" not in items and "database_url" not in items
    assert items["admin_origins"]["source"] == "env"  # set by conftest


def test_override_wins_over_env_and_reset_restores_it(client, h, monkeypatch):
    monkeypatch.setattr(settings, "notify_hourly_cap", 7)
    r = patch(client, h, notify_hourly_cap=12)
    assert r.status_code == 200, r.text
    item = by_key(r.json())["notify_hourly_cap"]
    assert (item["value"], item["env_value"], item["source"]) == (12, 7, "ui")
    assert settings.notify_hourly_cap == 12

    item = by_key(patch(client, h, notify_hourly_cap=None).json())["notify_hourly_cap"]
    assert item["value"] == 7 and item["source"] != "ui"
    assert settings.notify_hourly_cap == 7


def test_invalid_values_save_nothing(client, h, db):
    for changes in (
        {"notify_hourly_cap": 0},
        {"smtp_security": "tls"},
        {"public_url": "javascript:alert(1)"},
        {"mail_provider": "webhook"},
        {"smtp_port": 99999},
        {"notify_hourly_cap": 9, "trust_proxy": True},  # one bad key fails the whole request
        {"jwt_secret": "x" * 40},
    ):
        r = client.patch("/settings", json={"changes": changes}, headers=h)
        assert r.status_code == 422, changes
    assert db.scalars(select(AppSetting)).all() == []
    assert settings.notify_hourly_cap == 5 and not settings.trust_proxy


def test_secrets_are_write_only_and_encrypted(client, h, db):
    r = patch(client, h, smtp_password="hunter2-but-longer")
    assert r.status_code == 200
    item = by_key(r.json())["smtp_password"]
    assert item["configured"] and item["value"] is None and item["env_value"] is None
    assert "hunter2" not in r.text
    assert settings.smtp_password == "hunter2-but-longer"

    row = db.get(AppSetting, "smtp_password")
    assert "hunter2" not in str(row.value)
    (event,) = db.scalars(select(AuditEvent).where(AuditEvent.action == "settings.update")).all()
    assert event.details == {"smtp_password": "changed"}

    assert not by_key(patch(client, h, smtp_password=None).json())["smtp_password"]["configured"]


def test_changes_are_audited_with_old_and_new_values(client, h, db):
    patch(client, h, export_max_rows=500, notify_sender_name="Support")
    (event,) = db.scalars(select(AuditEvent).where(AuditEvent.action == "settings.update")).all()
    assert event.details["export_max_rows"] == {"from": 100_000, "to": 500, "reset": False}
    assert "Rows per CSV export" in event.summary
    patch(client, h, bulk_max_ids=None)  # no override to drop: nothing to record
    assert len(db.scalars(select(AuditEvent).where(AuditEvent.action == "settings.update")).all()) == 1


def test_other_processes_pick_up_saved_settings(client, h):
    """The worker applies what the API saved on its next pass."""
    patch(client, h, notify_max_recipients=3)
    runtime_settings.reset()
    assert settings.notify_max_recipients == 20
    with get_sessionmaker()() as db:
        runtime_settings.load(db)
    assert settings.notify_max_recipients == 3


def test_saved_values_that_became_invalid_are_ignored(db):
    db.add(AppSetting(key="trust_proxy", value=True, updated_by="x"))
    db.add(AppSetting(key="notify_hourly_cap", value=-1, updated_by="x"))
    db.commit()
    runtime_settings.load(db)
    assert not settings.trust_proxy and settings.notify_hourly_cap == 5


def test_secret_saved_under_another_key_falls_back_to_env(client, h, db, monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "from-env")
    patch(client, h, brevo_api_key="saved-in-ui")
    monkeypatch.setattr(settings, "settings_encryption_key", "a-rotated-key")
    runtime_settings.load(db)
    assert settings.brevo_api_key == "from-env"


@pytest.mark.parametrize("role", [Role.admin, Role.viewer])
def test_only_superadmins(client, db, role):
    user = make_user(db, "u@e.com")
    add_member(db, user, make_site(db), role)
    uh = login(client, "u@e.com")
    assert client.get("/settings", headers=uh).status_code == 403
    assert patch(client, uh, notify_hourly_cap=9).status_code == 403
    assert settings.notify_hourly_cap == 5

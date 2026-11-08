import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_token
from app.models import AuditEvent, PasswordResetToken, RefreshToken, User
from app.models.user import utcnow
from app.notifications import registry
from app.notifications.base import SendResult
from app.notifications.system_mail import mail_provider
from tests.conftest import login, make_user
from tests.test_auth import attempt_login
from tests.test_notifications import FakeProvider
from tests.test_totp import _enroll

PW = "correct-horse-battery"
NEW = "a-brand-new-passphrase"
PUBLIC = "https://admin.example.com"


@pytest.fixture
def mail(monkeypatch):
    """A configured mail provider that records what it is asked to send, and a PUBLIC_URL."""
    provider = FakeProvider()
    monkeypatch.setitem(registry._providers, "fake", provider)
    monkeypatch.setattr(settings, "public_url", PUBLIC)
    monkeypatch.setattr(settings, "mail_provider", "fake")  # whatever else is registered, mail goes here
    return provider


def request_reset(client, email="a@example.com"):
    return client.post("/auth/password-reset/request", json={"email": email})


def token_from(provider) -> str:
    link = re.search(r"https://\S+", provider.sent[-1].text).group(0)
    assert link.startswith(f"{PUBLIC}/reset-password#token=")
    return link.split("#token=")[1]


def confirm(client, token, password=NEW):
    return client.post("/auth/password-reset/confirm", json={"token": token, "new_password": password})


# --- availability -------------------------------------------------------------------------------


def reset_offered(client) -> bool:
    return client.get("/auth/features").json()["password_reset"]


def test_features_reflect_configuration(client, monkeypatch):
    assert reset_offered(client) is False  # nothing configured
    provider = FakeProvider()
    monkeypatch.setitem(registry._providers, "fake", provider)
    assert reset_offered(client) is False  # no PUBLIC_URL
    monkeypatch.setattr(settings, "public_url", PUBLIC)
    assert reset_offered(client) is True
    provider.configured = False
    assert reset_offered(client) is False  # nothing can send


def test_request_is_refused_when_unavailable(client, db):
    make_user(db, "a@example.com")
    assert request_reset(client).status_code == 404


def test_mail_provider_choice(monkeypatch):
    a, b = FakeProvider(), FakeProvider()
    b.key = "other"
    monkeypatch.setitem(registry._providers, "fake", a)
    monkeypatch.setitem(registry._providers, "other", b)
    assert mail_provider() in (a, b)
    monkeypatch.setattr(settings, "mail_provider", "other")
    assert mail_provider() is b
    monkeypatch.setattr(settings, "mail_provider", "nope")
    assert mail_provider() is None


# --- requesting ---------------------------------------------------------------------------------


def test_known_and_unknown_addresses_look_identical(client, db, mail):
    make_user(db, "a@example.com")
    known = request_reset(client, "a@example.com")
    unknown = request_reset(client, "nobody@example.com")
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert [m.to for m in mail.sent] == [["a@example.com"]]  # only the real account got mail


def test_email_is_matched_case_insensitively_and_sent_to_the_account(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client, "A@Example.COM")
    assert mail.sent[0].to == ["a@example.com"]
    assert mail.sent[0].subject == "Reset your Loupebox password"


def test_disabled_accounts_get_nothing(client, db, mail):
    user = make_user(db, "a@example.com")
    user.is_active = False
    db.commit()
    assert request_reset(client).status_code == 202
    assert mail.sent == [] and db.scalar(select(PasswordResetToken.id)) is None


def test_token_is_stored_hashed_and_expires_per_setting(client, db, mail, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_minutes", 7)
    make_user(db, "a@example.com")
    request_reset(client)
    token = token_from(mail)
    row = db.scalars(select(PasswordResetToken)).one()
    assert row.token_hash == hash_token(token) and token not in row.token_hash
    ttl = row.expires_at.replace(tzinfo=None) - utcnow().replace(tzinfo=None)
    assert timedelta(minutes=6) < ttl <= timedelta(minutes=7)
    assert "expires in 7 minutes" in mail.sent[0].text
    assert "7 minutes" in mail.sent[0].html


def test_email_contents(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    msg = mail.sent[0]
    token = token_from(mail)
    assert f'href="{PUBLIC}/reset-password#token={token}"' in msg.html
    assert "ignore this email" in msg.text and msg.tags == ["password-reset"]


def test_a_newer_request_replaces_the_older_link(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    first = token_from(mail)
    request_reset(client)
    second = token_from(mail)
    assert first != second
    assert confirm(client, first).status_code == 400
    assert confirm(client, second).status_code == 200


def test_send_failures_do_not_break_the_request(client, db, mail):
    make_user(db, "a@example.com")
    mail.results = [SendResult.failed("provider down")]
    assert request_reset(client).status_code == 202


def test_a_provider_that_raises_does_not_break_the_request(client, db, mail):
    make_user(db, "a@example.com")

    def boom(*_a, **_k):
        raise RuntimeError("smtp exploded")

    mail.send = boom
    assert request_reset(client).status_code == 202


def test_request_rate_limits(client, db, mail):
    make_user(db, "a@example.com")
    codes = [request_reset(client).status_code for _ in range(settings.password_reset_email_limit + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {202}
    # The limit is per address, applied whether or not the account exists.
    codes = [
        request_reset(client, "ghost@example.com").status_code
        for _ in range(settings.password_reset_email_limit + 1)
    ]
    assert codes[-1] == 429


def test_ip_rate_limit(client, db, mail, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_email_limit", 100)
    codes = [
        request_reset(client, f"u{i}@example.com").status_code
        for i in range(settings.password_reset_ip_limit + 1)
    ]
    assert codes[-1] == 429


# --- confirming ---------------------------------------------------------------------------------


def test_reset_clears_failed_sign_ins(client, db, mail, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)
    make_user(db, "a@example.com")
    for i in range(settings.login_failure_limit):
        attempt_login(client, f"10.0.0.{i}")
    assert attempt_login(client, "10.0.1.1", password=PW) == 429
    request_reset(client)
    assert confirm(client, token_from(mail)).status_code == 200
    assert attempt_login(client, "10.0.1.2", password=NEW) == 200


def test_reset_changes_the_password_and_signs_everyone_out(client, db, mail):
    make_user(db, "a@example.com")
    login(client, "a@example.com")
    login(client, "a@example.com")
    request_reset(client)
    r = confirm(client, token_from(mail))
    assert r.status_code == 200
    assert all(t.revoked_at for t in db.scalars(select(RefreshToken)))
    assert client.post("/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 401
    assert client.post("/auth/login", json={"email": "a@example.com", "password": NEW}).status_code == 200


def test_reset_does_not_log_the_user_in(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    r = confirm(client, token_from(mail))
    assert "access_token" not in r.text and "refresh_token" not in client.cookies


def test_token_works_once(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    token = token_from(mail)
    assert confirm(client, token).status_code == 200
    again = confirm(client, token, "yet-another-passphrase")
    assert again.status_code == 400
    assert client.post("/auth/login", json={"email": "a@example.com", "password": NEW}).status_code == 200


def test_expired_token_is_refused(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    token = token_from(mail)
    row = db.scalars(select(PasswordResetToken)).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert confirm(client, token).status_code == 400
    assert client.post("/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 200


@pytest.mark.parametrize("bad", ["", "junk", "x" * 300])
def test_unknown_tokens_are_refused_uniformly(client, db, mail, bad):
    make_user(db, "a@example.com")
    r = confirm(client, bad)
    assert r.status_code in (400, 422)
    if r.status_code == 400:
        assert r.json()["detail"] == "This reset link is invalid or has expired"


def test_weak_password_is_refused_and_the_link_survives(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    token = token_from(mail)
    assert confirm(client, token, "short").status_code == 422
    assert confirm(client, token).status_code == 200


def test_disabling_the_account_after_requesting_blocks_the_link(client, db, mail):
    user = make_user(db, "a@example.com")
    request_reset(client)
    token = token_from(mail)
    user.is_active = False
    db.commit()
    assert confirm(client, token).status_code == 400


def test_two_factor_survives_a_reset(client, db, mail):
    _enroll(client, db)
    client.cookies.clear()
    request_reset(client)
    assert confirm(client, token_from(mail)).status_code == 200
    r = client.post("/auth/login", json={"email": "a@example.com", "password": NEW})
    assert r.json().get("mfa_required") is True and "access_token" not in r.json()
    assert db.scalar(select(User.totp_enabled_at)) is not None


def test_changed_email_is_sent(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    confirm(client, token_from(mail))
    assert len(mail.sent) == 2
    assert mail.sent[1].to == ["a@example.com"] and mail.sent[1].tags == ["password-changed"]
    assert "was just changed" in mail.sent[1].text


def test_reset_is_audited_without_secrets(client, db, mail):
    make_user(db, "a@example.com")
    request_reset(client)
    token = token_from(mail)
    confirm(client, token)
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.password_reset")).one()
    assert ev.actor_email == "a@example.com" and ev.details == {"password": "changed"}
    dump = ev.summary + str(ev.details)
    assert token not in dump and NEW not in dump
    assert db.scalars(select(AuditEvent)).all() == [ev]  # the request itself isn't logged


def test_confirm_attempts_are_rate_limited(client, db, mail):
    codes = [confirm(client, "junk").status_code for _ in range(settings.login_ip_limit + 1)]
    assert codes[-1] == 429

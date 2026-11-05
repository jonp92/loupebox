import email
import smtplib
import ssl
import time
from email import policy

import pytest

from app.core.config import settings
from app.models import OutboxStatus
from app.notifications import registry
from app.notifications.base import Message
from app.notifications.dispatcher import process_due
from app.notifications.providers import smtp
from tests.conftest import make_site
from tests.fake_smtp import FakeSmtp, make_cert
from tests.test_notification_api import admin, url  # noqa: F401  (fixtures)
from tests.test_notifications import make_channel, outbox, submit

SENDER = "feedback@example.com"


@pytest.fixture
def cert(tmp_path):
    return make_cert(tmp_path)


@pytest.fixture
def serve(monkeypatch, cert):
    """Start a fake server in the given mode and point the settings (and trust store) at it."""
    started: list[FakeSmtp] = []

    def start(mode="plain", *, credentials=None, trust=True, **settings_override) -> FakeSmtp:
        server = FakeSmtp(mode=mode, credentials=credentials, cert=cert[:2]).start()
        started.append(server)
        for name, value in {
            "smtp_host": "localhost",
            "smtp_port": server.port,
            "notify_sender_email": SENDER,
            "notify_sender_name": "Loupebox",
            "smtp_security": {"plain": "none"}.get(mode, "ssl" if mode == "ssl" else "starttls"),
            "smtp_username": "",
            "smtp_password": "",
            "smtp_timeout": 3,
            **settings_override,
        }.items():
            monkeypatch.setattr(settings, name, value)
        if trust:
            context = ssl.create_default_context(cadata=cert[2])
            monkeypatch.setattr(smtp, "_tls_context", lambda: context)
        return server

    yield start
    for server in started:
        server.stop()


def send(*, to=("a@example.com",), **kw):
    provider = registry.get_provider("smtp")
    message = Message(
        to=list(to), subject=kw.pop("subject", "Hi"), text="plain body", html="<p>html body</p>", **kw
    )
    return provider.send(message, provider.ConfigModel())


def parsed(received) -> email.message.EmailMessage:
    return email.message_from_bytes(received.data, policy=policy.default)


# --- configuration ------------------------------------------------------------------------------


def test_registered_and_configuration_rules(monkeypatch):
    provider = registry.get_provider("smtp")
    assert provider is not None and provider.uses_recipients and not provider.signs
    assert not provider.is_configured()  # isolated from any real .env
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    assert not provider.is_configured()  # no sender yet
    monkeypatch.setattr(settings, "notify_sender_email", SENDER)
    assert provider.is_configured()
    monkeypatch.setattr(settings, "smtp_host", "")
    assert not provider.is_configured()


def test_credentials_are_never_sent_without_encryption(monkeypatch):
    provider = registry.get_provider("smtp")
    monkeypatch.setattr(settings, "smtp_host", "relay.internal")
    monkeypatch.setattr(settings, "notify_sender_email", SENDER)
    monkeypatch.setattr(settings, "smtp_security", "none")
    assert provider.is_configured()  # an open relay on a private network is fine
    monkeypatch.setattr(settings, "smtp_username", "user")
    assert not provider.is_configured()  # but a password over plaintext is not


# --- delivery -----------------------------------------------------------------------------------


def test_message_shape(serve):
    server = serve("plain")
    result = send(
        to=["a@example.com", "b@example.com"], reply_to="user@example.com", tags=["feedback.created"]
    )
    assert result.status == "sent" and result.message_id and result.message_id.startswith("<")
    assert len(server.messages) == 2  # one per recipient: they never see each other
    first = parsed(server.messages[0])
    assert server.messages[0].rcpt == ["a@example.com"] and server.messages[0].mail_from == SENDER
    assert first["To"] == "a@example.com" and "b@example.com" not in server.messages[0].data.decode()
    assert first["From"] == f"Loupebox <{SENDER}>" and first["Subject"] == "Hi"
    assert first["Reply-To"] == "user@example.com" and first["X-Loupebox-Tags"] == "feedback.created"
    assert first["Message-ID"].endswith("@example.com>") and first["Date"]
    assert first.get_body(("plain",)).get_content().strip() == "plain body"
    assert first.get_body(("html",)).get_content().strip() == "<p>html body</p>"
    assert server.ehlo_names == ["example.com"]  # the sender's domain, not the container's hostname


def test_non_ascii_content(serve):
    server = serve("plain")
    assert send(subject="Héllo — ünïcode ✓").status == "sent"
    assert parsed(server.messages[0])["Subject"] == "Héllo — ünïcode ✓"


def test_starttls_upgrades_before_any_mail(serve):
    server = serve("starttls")
    assert send().status == "sent"
    assert server.messages[0].tls and server.plaintext_mail_attempts == 0


def test_implicit_tls(serve):
    server = serve("ssl")
    assert send().status == "sent" and server.messages[0].tls


def test_starttls_is_required_never_downgraded(serve):
    server = serve("no-starttls", smtp_security="starttls")
    result = send()
    assert result.status == "failed" and "STARTTLS" in result.error
    assert server.messages == [] and server.plaintext_mail_attempts == 0


def test_untrusted_certificate_is_refused(serve):
    server = serve("starttls", trust=False)
    result = send()
    assert result.status == "failed" and "certificate" in result.error
    assert server.messages == []


def test_auth_success_and_failure(serve):
    server = serve(
        "starttls", credentials=("mailer", "s3cret-pass"), smtp_username="mailer", smtp_password="s3cret-pass"
    )
    assert send().status == "sent" and server.auth_attempts == [("mailer", "s3cret-pass")]

    bad = serve(
        "starttls",
        credentials=("mailer", "s3cret-pass"),
        smtp_username="mailer",
        smtp_password="wrong-pass-123",
    )
    result = send()
    assert result.status == "failed" and "535" in result.error
    assert "wrong-pass-123" not in result.error and "s3cret-pass" not in result.error
    assert bad.messages == []


def test_recipient_outcomes(serve):
    server = serve("plain")
    assert send(to=["refuse@example.com"]).status == "failed"
    assert send(to=["defer@example.com"]).status == "retry"
    # One refused address doesn't stop the others being delivered, but the result is still a failure.
    mixed = send(to=["good@example.com", "refuse@example.com", "good2@example.com"])
    assert mixed.status == "failed" and "550" in mixed.error
    assert [m.rcpt for m in server.messages] == [["good@example.com"], ["good2@example.com"]]
    # A deferral anywhere wins: the whole message is retried (at least once).
    assert send(to=["good@example.com", "defer@example.com", "refuse@example.com"]).status == "retry"


def test_connection_dropping_mid_send_retries(serve):
    server = serve("plain")
    result = send(to=["good@example.com", "hangup@example.com", "late@example.com"])
    assert result.status == "retry"
    assert [m.rcpt for m in server.messages] == [["good@example.com"]]  # the rest wait for the retry


def test_unreachable_server_retries(serve, monkeypatch):
    serve("plain")
    monkeypatch.setattr(settings, "smtp_port", 1)  # nothing listens here
    assert send().status == "retry"


def test_timeout_retries(serve, monkeypatch):
    server = serve("plain")
    server.silent = True
    monkeypatch.setattr(settings, "smtp_timeout", 1)
    started = time.monotonic()
    result = send()
    assert result.status == "retry" and time.monotonic() - started < 4


def test_header_injection_is_not_possible(serve):
    server = serve("plain")
    # A submitter's address with line breaks is dropped, not copied into a header.
    assert send(reply_to="x@y.com\r\nBcc: victim@example.com").status == "sent"
    sent = server.messages[0].data.decode()
    assert "Bcc:" not in sent and "Reply-To" not in sent
    # A subject with a line break makes the message unbuildable, which is permanent.
    result = send(subject="Hi\r\nBcc: victim@example.com")
    assert result.status == "failed" and len(server.messages) == 1


# --- through the app ----------------------------------------------------------------------------


def test_feedback_notification_end_to_end(client, db, serve):
    server = serve("starttls", credentials=("u", "p"), smtp_username="u", smtp_password="p")
    site = make_site(db)
    make_channel(db, site, provider="smtp", extra_recipients=["ops@example.com"])
    assert submit(client, "the page is broken").status_code == 201
    assert process_due(db) == 1
    [row] = outbox(db)
    assert row.status == OutboxStatus.sent
    [received] = server.messages
    assert received.rcpt == ["ops@example.com"]
    assert "the page is broken" in parsed(received).get_body(("plain",)).get_content()


def test_hourly_cap_and_summary_apply_to_smtp_like_any_email_provider(client, db, serve, monkeypatch):
    serve("plain")
    monkeypatch.setattr(settings, "public_ip_limit", 100)
    site = make_site(db)
    make_channel(db, site, provider="smtp")
    for i in range(settings.notify_hourly_cap + 2):
        submit(client, f"message number {i}")
    process_due(db, limit=50)
    assert {r.status for r in outbox(db)} == {OutboxStatus.sent, OutboxStatus.held}


def test_send_test_through_the_api(client, db, admin, serve):
    server = serve("plain")
    site, h = admin
    channel = make_channel(db, site, provider="smtp")
    r = client.post(url(site, f"/{channel.id}/test"), headers=h)
    assert r.json() == {"status": "sent", "error": None, "to": "admin@example.com"}
    assert server.messages[0].rcpt == ["admin@example.com"]


def test_creating_a_channel_needs_the_server_to_be_configured(client, admin):
    site, h = admin
    body = {"provider": "smtp", "name": "Mail"}
    assert client.post(url(site), headers=h, json=body).status_code == 409


def test_smtp_secrets_never_appear_in_responses(client, db, admin, serve):
    serve("plain", credentials=None, smtp_password="PASSWORD-SHOULD-NOT-LEAK")
    site, h = admin
    channel = make_channel(db, site, provider="smtp")
    for path in (
        "/notifications/providers",
        f"/sites/{site.id}/notifications",
        f"/sites/{site.id}/notifications/deliveries",
    ):
        assert "PASSWORD-SHOULD-NOT-LEAK" not in client.get(path, headers=h).text
    client.post(url(site, f"/{channel.id}/test"), headers=h)
    assert "PASSWORD-SHOULD-NOT-LEAK" not in client.get(url(site, "/deliveries"), headers=h).text


def test_password_reset_can_use_smtp(client, db, serve, monkeypatch):
    from tests.conftest import make_user

    server = serve("starttls")
    monkeypatch.setattr(settings, "public_url", "https://admin.example.com")
    monkeypatch.setattr(settings, "mail_provider", "smtp")
    make_user(db, "a@example.com")
    assert client.get("/auth/features").json() == {"password_reset": True}
    assert client.post("/auth/password-reset/request", json={"email": "a@example.com"}).status_code == 202
    [received] = server.messages
    assert received.rcpt == ["a@example.com"] and received.tls
    assert (
        "https://admin.example.com/reset-password#token="
        in parsed(received).get_body(("plain",)).get_content()
    )


def test_classification_of_smtp_errors():
    c = smtp._classify
    assert c(smtplib.SMTPServerDisconnected()).status == "retry"
    assert c(smtplib.SMTPConnectError(421, b"busy")).status == "retry"
    assert c(smtplib.SMTPAuthenticationError(454, b"temporary")).status == "retry"
    assert c(smtplib.SMTPAuthenticationError(535, b"bad")).status == "failed"
    assert c(smtplib.SMTPSenderRefused(550, b"no", "x@y")).status == "failed"
    assert c(smtplib.SMTPDataError(554, b"spam")).status == "failed"
    assert c(smtplib.SMTPDataError(451, b"later")).status == "retry"
    assert c(TimeoutError()).status == "retry"
    assert c(ConnectionResetError()).status == "retry"

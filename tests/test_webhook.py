import base64
import hashlib
import hmac
import json
import socket

import httpx
import pytest
from sqlalchemy import select

from app.core import crypto, netguard
from app.core.config import settings
from app.models import AuditEvent, NotificationChannel, OutboxStatus
from app.notifications.dispatcher import process_due
from app.notifications.providers import webhook
from tests.conftest import make_site
from tests.test_notification_api import admin, url  # noqa: F401  (fixtures)
from tests.test_notifications import fake, make_channel, outbox, submit  # noqa: F401

PUBLIC = "93.184.216.34"
HOOK = "https://hooks.example.com/ganymede"
SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Fake resolver: name -> list of addresses."""
    table = {"hooks.example.com": [PUBLIC]}

    def fake(host, port, **_kw):
        if host not in table:
            raise socket.gaierror("not found")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]

    monkeypatch.setattr(netguard, "_getaddrinfo", fake)
    return table


@pytest.fixture
def receiver(monkeypatch):
    """Stands in for the network: records requests, answers with `.status`."""

    class Receiver:
        def __init__(self):
            self.status = 200
            self.requests: list[httpx.Request] = []
            self.error: Exception | None = None

        def handler(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.error:
                raise self.error
            return httpx.Response(self.status, text="ignored body")

    r = Receiver()
    monkeypatch.setattr(webhook, "_transport", lambda: httpx.MockTransport(r.handler))
    return r


def make_webhook(db, site, url_=HOOK, secret=SECRET, **kw):
    channel = make_channel(db, site, provider="webhook", extra_recipients=[], **kw)
    channel.config = {"url": url_}
    channel.secret = crypto.encrypt("webhook", secret)
    db.commit()
    return channel, secret


def expected_signature(secret, msg_id, ts, body):
    key = base64.b64decode(secret.removeprefix("whsec_"))
    return "v1," + base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()


# --- netguard -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "http://hooks.example.com/x",  # plain http
        "ftp://hooks.example.com/x",
        "https://user:pw@hooks.example.com/x",
        "https:///nohost",
        "https://127.0.0.1/x",
        "https://10.0.0.5/x",
        "https://192.168.1.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://100.64.0.1/x",
        "https://[::1]/x",
        "https://[::ffff:127.0.0.1]/x",
        "https://[fe80::1]/x",
        "https://[64:ff9b::7f00:1]/x",
        "https://0.0.0.0/x",
    ],
)
def test_static_checks_reject(bad):
    with pytest.raises(netguard.UnsafeTarget):
        netguard.parse(bad, allow_private=False)


@pytest.mark.parametrize("answer", [["127.0.0.1"], ["10.1.2.3"], [PUBLIC, "169.254.169.254"], ["::1"], ["::ffff:10.0.0.1"]])
def test_resolution_to_private_is_refused(dns, answer):
    dns["hooks.example.com"] = answer
    with pytest.raises(netguard.UnsafeTarget):
        netguard.resolve(HOOK, allow_private=False)


def test_resolve_pins_the_checked_address():
    [target] = netguard.resolve("https://hooks.example.com:8443/a/b?x=1", allow_private=False)
    assert target.url == f"https://{PUBLIC}:8443/a/b?x=1"
    assert target.host_header == "hooks.example.com:8443" and target.tls_name == "hooks.example.com"


def test_unresolvable_host_is_a_resolution_error():
    with pytest.raises(netguard.ResolutionError):
        netguard.resolve("https://nope.example.com/", allow_private=False)


def test_allow_private_opts_in(dns):
    dns["hooks.example.com"] = ["10.1.2.3"]
    assert netguard.resolve("http://hooks.example.com/x", allow_private=True)[0].ip == "10.1.2.3"
    assert netguard.parse("http://127.0.0.1:9000/x", allow_private=True)[2] == 9000


# --- provider -----------------------------------------------------------------------------------


def event():
    return {"id": "evt-1", "type": "feedback.created", "created_at": "2026-11-02T00:00:00+00:00",
            "site": {"id": "s", "name": "Shop"}, "data": {"excerpt": "héllo"}}


def send(message_event=None, secret=SECRET, url_=HOOK):
    msg = webhook.Message(to=[], subject="", text="", event=message_event or event(), secret=secret)
    return webhook.WebhookProvider().send(msg, webhook.WebhookConfig(url=url_))


def test_request_is_signed_and_pinned(receiver):
    result = send()
    assert result.status == "sent" and result.message_id == "evt-1"
    [req] = receiver.requests
    assert req.url.host == PUBLIC and req.headers["host"] == "hooks.example.com"
    assert req.headers["content-type"] == "application/json"
    assert req.extensions.get("sni_hostname") == "hooks.example.com"
    body = req.content
    assert json.loads(body) == event()
    assert req.headers["webhook-id"] == "evt-1"
    ts = req.headers["webhook-timestamp"]
    assert req.headers["webhook-signature"] == expected_signature(SECRET, "evt-1", ts, body)
    # Tampering with the body breaks the signature.
    assert req.headers["webhook-signature"] != expected_signature(SECRET, "evt-1", ts, body + b" ")


@pytest.mark.parametrize(
    "status,expected",
    [(200, "sent"), (204, "sent"), (301, "failed"), (302, "failed"), (400, "failed"), (401, "failed"),
     (404, "failed"), (410, "failed"), (408, "retry"), (429, "retry"), (500, "retry"), (503, "retry")],
)
def test_status_mapping(receiver, status, expected):
    receiver.status = status
    assert send().status == expected


def test_redirects_are_not_followed(receiver):
    receiver.status = 302
    result = send()
    assert result.status == "failed" and "redirect" in result.error
    assert len(receiver.requests) == 1


def test_network_errors_retry(receiver):
    receiver.error = httpx.ReadTimeout("slow")
    assert send().status == "retry"
    receiver.error = httpx.ConnectError("refused")
    assert send().status == "retry"


def test_tries_the_next_address_when_connect_fails(receiver, dns, monkeypatch):
    dns["hooks.example.com"] = ["93.184.216.35", PUBLIC]
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200)

    monkeypatch.setattr(webhook, "_transport", lambda: httpx.MockTransport(handler))
    assert send().status == "sent" and calls == ["93.184.216.35", PUBLIC]


def test_rebinding_after_save_is_blocked_at_send(receiver, dns):
    dns["hooks.example.com"] = ["169.254.169.254"]  # was public when the channel was saved
    result = send()
    assert result.status == "failed" and "blocked" in result.error
    assert receiver.requests == []


def test_dns_failure_retries(receiver):
    result = send(url_="https://nope.example.com/")
    assert result.status == "retry" and receiver.requests == []


def test_no_secret_means_nothing_is_sent(receiver):
    assert send(secret=None).status == "failed" and receiver.requests == []


def test_proxy_environment_is_ignored(receiver, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    assert send().status == "sent"


# --- API ----------------------------------------------------------------------------------------


def create(client, site, h, **body):
    return client.post(url(site), headers=h, json={"provider": "webhook", "name": "Hook", "config": {"url": HOOK}, **body})


def test_create_returns_the_secret_once_and_stores_it_encrypted(client, db, admin):
    site, h = admin
    r = create(client, site, h)
    assert r.status_code == 201, r.text
    secret = r.json()["secret"]
    assert secret.startswith("whsec_") and r.json()["has_secret"] is True

    listed = client.get(url(site), headers=h).json()[0]
    assert listed["has_secret"] is True and "secret" not in listed
    stored = db.scalar(select(NotificationChannel.secret))
    assert stored and secret not in stored and crypto.decrypt("webhook", stored) == secret
    assert secret not in client.get(url(site), headers=h).text


@pytest.mark.parametrize(
    "bad",
    ["http://hooks.example.com/x", "https://127.0.0.1/x", "https://localhost/x", "https://nope.example.com/x", "not a url", ""],
)
def test_create_rejects_unsafe_or_unresolvable_urls(client, db, admin, bad):
    site, h = admin
    r = create(client, site, h, config={"url": bad})
    assert r.status_code == 422, r.text
    assert db.scalar(select(NotificationChannel.id)) is None


def test_localhost_name_is_rejected_via_resolution(client, admin, dns):
    site, h = admin
    dns["internal.example.com"] = ["10.0.0.9"]
    r = create(client, site, h, config={"url": "https://internal.example.com/x"})
    assert r.status_code == 422 and "private" in r.text


def test_update_revalidates_the_url(client, admin):
    site, h = admin
    cid = create(client, site, h).json()["id"]
    assert client.patch(url(site, f"/{cid}"), headers=h, json={"config": {"url": "https://10.0.0.1/x"}}).status_code == 422
    assert client.patch(url(site, f"/{cid}"), headers=h, json={"config": {"url": HOOK + "/v2"}}).status_code == 200


def test_rotate_secret(client, db, admin):
    site, h = admin
    made = create(client, site, h).json()
    r = client.post(url(site, f"/{made['id']}/rotate-secret"), headers=h)
    assert r.status_code == 200 and r.json()["secret"] != made["secret"]
    assert crypto.decrypt("webhook", db.scalar(select(NotificationChannel.secret))) == r.json()["secret"]
    event_ = db.scalars(select(AuditEvent).where(AuditEvent.action == "channel.rotate_secret")).one()
    assert r.json()["secret"] not in json.dumps(event_.details) + event_.summary


def test_rotate_is_refused_for_providers_without_a_secret(client, db, admin, fake):
    site, h = admin
    channel = make_channel(db, site)
    assert client.post(url(site, f"/{channel.id}/rotate-secret"), headers=h).status_code == 400


def test_provider_list_describes_webhook(client, admin):
    _, h = admin
    info = {p["key"]: p for p in client.get("/notifications/providers", headers=h).json()}["webhook"]
    assert info["configured"] and info["signs"] and info["uses_recipients"] is False
    assert info["config_schema"]["required"] == ["url"]


def test_send_test_posts_a_test_event(client, db, admin, receiver):
    site, h = admin
    made = create(client, site, h).json()
    r = client.post(url(site, f"/{made['id']}/test"), headers=h)
    assert r.json() == {"status": "sent", "error": None, "to": None}
    [req] = receiver.requests
    body = json.loads(req.content)
    assert body["type"] == "test" and body["site"]["name"] == site.name
    assert req.headers["webhook-signature"] == expected_signature(made["secret"], body["id"], req.headers["webhook-timestamp"], req.content)


def test_secrets_never_leak_into_audit_or_listing(client, db, admin):
    site, h = admin
    made = create(client, site, h).json()
    dump = json.dumps([[e.summary, e.details] for e in db.scalars(select(AuditEvent))])
    assert made["secret"] not in dump and HOOK not in dump


# --- delivery -----------------------------------------------------------------------------------


def test_feedback_is_delivered_without_recipients(client, db, receiver):
    site = make_site(db)
    _, secret = make_webhook(db, site)
    assert submit(client, "Great shop").status_code == 201
    assert process_due(db) == 1
    [row] = outbox(db)
    assert row.status == OutboxStatus.sent
    [req] = receiver.requests
    body = json.loads(req.content)
    assert body["type"] == "feedback.created" and body["id"] == str(row.id)
    assert body["site"] == {"id": str(site.id), "name": site.name}
    assert body["data"]["excerpt"] == "Great shop" and "type" not in body["data"]
    assert req.headers["webhook-signature"] == expected_signature(secret, body["id"], req.headers["webhook-timestamp"], req.content)


def test_webhooks_are_not_held_by_the_email_cap(client, db, receiver, monkeypatch):
    site = make_site(db)
    make_webhook(db, site)
    monkeypatch.setattr(settings, "public_ip_limit", 100)
    n = settings.notify_hourly_cap + 3
    for i in range(n):
        assert submit(client, f"message number {i}").status_code == 201
    process_due(db, limit=50)
    assert {r.status for r in outbox(db)} == {OutboxStatus.sent} and len(receiver.requests) == n


def test_retry_keeps_the_same_event_id(client, db, receiver):
    site = make_site(db)
    make_webhook(db, site)
    submit(client)
    receiver.status = 503
    process_due(db)
    [row] = outbox(db)
    assert row.status == OutboxStatus.pending and "503" in row.last_error
    row.next_attempt_at = row.created_at
    db.commit()
    receiver.status = 200
    process_due(db)
    assert {r.headers["webhook-id"] for r in receiver.requests} == {str(row.id)} and len(receiver.requests) == 2


def test_unreadable_secret_fails_permanently(client, db, receiver, monkeypatch):
    site = make_site(db)
    make_webhook(db, site)
    submit(client)
    monkeypatch.setattr(settings, "webhook_encryption_key", "a-different-key")
    process_due(db)
    [row] = outbox(db)
    assert row.status == OutboxStatus.failed and "WEBHOOK_ENCRYPTION_KEY" in row.last_error
    assert receiver.requests == []


def test_blocked_target_fails_permanently_and_sends_nothing(client, db, receiver, dns):
    site = make_site(db)
    make_webhook(db, site)
    submit(client)
    dns["hooks.example.com"] = ["10.0.0.1"]
    process_due(db)
    [row] = outbox(db)
    assert row.status == OutboxStatus.failed and "blocked" in row.last_error and receiver.requests == []

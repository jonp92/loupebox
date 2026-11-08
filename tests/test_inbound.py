import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.inbound import registry
from app.inbound.base import InboundMessage, PollingSource
from app.inbound.ingest import Outcome, ingest
from app.inbound.mime import parse_message
from app.inbound.sources import imap
from app.inbound.text import strip_quoted
from app.inbound.token import feedback_id_from_address, reply_address
from app.models import Feedback, FeedbackReply, FeedbackStatus, NotificationOutbox, Role, Site
from app.notifications import registry as providers
from tests.conftest import make_site
from tests.test_bulk_filters import as_role, seed
from tests.test_notifications import FakeProvider, make_channel
from tests.test_webhook import dns, make_webhook  # noqa: F401 (fixture; dns is autouse)

PERSON = "visitor@example.org"
INBOX = "replies@example.com"


@pytest.fixture
def inbound(monkeypatch):
    monkeypatch.setattr(settings, "inbound_address", INBOX)
    monkeypatch.setattr(settings, "imap_host", "imap.test")


@pytest.fixture
def item(db):
    return seed(db, make_site(db, "Shop"), message="The cart is broken", email=PERSON)


def mail(*, sender=PERSON, to=INBOX, body="It works now, thanks.", **headers) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, to
    msg["Subject"] = "Re: your feedback"
    msg["Message-ID"] = headers.pop("message_id", f"<{uuid.uuid4()}@client.test>")
    for name, value in headers.items():
        msg[name.replace("_", "-")] = value
    msg.set_content(body)
    return msg.as_bytes()


def inbound_for(item, **kw) -> InboundMessage:
    return parse_message(mail(to=reply_address(item.id), **kw))


# -- address token ---------------------------------------------------------------------------------------


def test_token_round_trip_and_tamper(inbound):
    fid = uuid.uuid4()
    address = reply_address(fid)
    assert address.startswith("replies+") and address.endswith("@example.com")
    assert feedback_id_from_address(address) == fid
    assert feedback_id_from_address(address.upper()) == fid
    local, _, domain = address.partition("@")
    assert feedback_id_from_address(f"{local[:-1]}{'0' if local[-1] != '0' else '1'}@{domain}") is None
    assert feedback_id_from_address(address.replace("replies+", "other+")) is None
    assert feedback_id_from_address(address.replace("@example.com", "@evil.test")) is None
    assert feedback_id_from_address(INBOX) is None and feedback_id_from_address("nonsense") is None


def test_no_address_while_inbound_is_off():
    assert reply_address(uuid.uuid4()) is None


# -- quoted text ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Thanks!\n\nOn Tue, Nov 3, 2026 at 9:14 AM Shop <a@b.c> wrote:\n> We fixed it.\n",
        "Thanks!\n\nOn Tue, Nov 3, 2026 at 9:14 AM Shop <a@b.c>\nwrote:\n> We fixed it.\n",
        "Thanks!\n\n-----Original Message-----\nFrom: x\nSent: y\n",
        "Thanks!\n\nFrom: Shop <a@b.c>\nSent: Tuesday\nTo: me\nSubject: Re\n\nWe fixed it.",
        "Thanks!\n-- \nA. Visitor\n",
        "Thanks!\n> We fixed it.\n> Really.\n",
    ],
)
def test_quoted_thread_is_cut(text):
    assert strip_quoted(text) == "Thanks!"


def test_inline_answers_between_quoted_lines_are_kept():
    text = "> Did it break on checkout?\nYes, on checkout.\n> Which browser?\nSafari."
    assert strip_quoted(text) == text


# -- parsing -------------------------------------------------------------------------------------------


def test_parse_reads_ids_and_plus_address():
    fid = uuid.uuid4()
    raw = mail(
        to=f"Shop <{INBOX}>, other@x.test",
        Delivered_To=f"replies+{fid.hex}abc@example.com",
        in_reply_to="<m-1@shop.test>",
        references="<a@x> <m-1@shop.test>",
    )
    msg = parse_message(raw)
    assert (
        msg.sender == PERSON
        and INBOX in msg.recipients
        and f"replies+{fid.hex}abc@example.com" in msg.recipients
    )
    assert msg.in_reply_to == "m-1@shop.test" and msg.references == ["a@x", "m-1@shop.test"]
    assert msg.kind == "reply" and msg.text.strip() == "It works now, thanks."


@pytest.mark.parametrize(
    "headers",
    [
        {"Auto_Submitted": "auto-replied"},
        {"Precedence": "bulk"},
        {"X_Autoreply": "yes"},
        {"Return_Path": "<>"},
    ],
)
def test_robots_are_classified_auto(headers):
    assert parse_message(mail(**headers)).kind == "auto"
    assert parse_message(mail(Auto_Submitted="no")).kind == "reply"


def test_html_only_mail_is_reduced_to_text():
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Message-ID"] = PERSON, INBOX, "<h@x>"
    msg.set_content("<p>Hello<br>there</p><div>Bye</div>", subtype="html")
    assert parse_message(msg.as_bytes()).text.split() == ["Hello", "there", "Bye"]


def dsn(original_id="m-1@shop.test", status="5.1.1") -> bytes:
    raw = (
        "From: MAILER-DAEMON@mx.test\nTo: bounces@example.com\nSubject: Undelivered\n"
        "Message-ID: <dsn@mx.test>\nMIME-Version: 1.0\n"
        'Content-Type: multipart/report; report-type=delivery-status; boundary="b"\n\n'
        "--b\nContent-Type: text/plain\n\nThe address was not found: visitor@example.org\n"
        "--b\nContent-Type: message/delivery-status\n\nReporting-MTA: dns; mx.test\n\n"
        f"Final-Recipient: rfc822; {PERSON}\nStatus: {status}\nDiagnostic-Code: smtp; 550 no such user\n"
        f"--b\nContent-Type: message/rfc822\n\nMessage-ID: <{original_id}>\n"
        "Subject: Re: your feedback\n\nbody\n--b--\n"
    )
    return raw.encode()


def test_delivery_report_is_a_bounce_with_the_original_id_and_code_but_no_text():
    msg = parse_message(dsn())
    assert (msg.kind, msg.bounced_message_id, msg.bounce_code, msg.text) == (
        "bounce",
        "m-1@shop.test",
        "5.1.1",
        "",
    )


# -- ingest --------------------------------------------------------------------------------------------


def stored(db):
    return db.scalars(select(FeedbackReply).where(FeedbackReply.direction == "inbound")).all()


def test_reply_by_token_is_stored_in_the_conversation(db, inbound, item):
    out = ingest(db, inbound_for(item, body="Fixed, thanks!\n\nOn Mon, X wrote:\n> old"))
    db.commit()
    assert out is Outcome.stored
    (reply,) = stored(db)
    assert (reply.body, reply.direction, reply.source, reply.status, reply.author_id) == (
        "Fixed, thanks!",
        "inbound",
        "email",
        "sent",
        None,
    )
    assert reply.feedback_id == item.id and reply.message_id.endswith("@client.test")


def test_reply_matches_by_threading_headers_when_the_token_is_lost(db, inbound, item):
    db.add(FeedbackReply(feedback_id=item.id, body="Hello", status="sent", message_id="<m-1@shop.test>"))
    db.commit()
    msg = parse_message(mail(to="somebody@else.test", in_reply_to="<m-1@shop.test>"))
    assert ingest(db, msg) is Outcome.stored
    assert stored(db)[0].feedback_id == item.id


def test_only_the_person_who_wrote_the_feedback_can_answer(db, inbound, item):
    assert ingest(db, inbound_for(item, sender="stranger@evil.test")) is Outcome.unmatched
    assert ingest(db, inbound_for(item, sender=PERSON.upper())) is Outcome.stored
    assert len(stored(db)) == 1


def test_unknown_token_and_no_match_are_dropped(db, inbound, item):
    msg = parse_message(mail(to=reply_address(uuid.uuid4())))
    assert ingest(db, msg) is Outcome.unmatched
    assert stored(db) == []


def test_the_same_message_is_stored_once(db, inbound, item):
    first = inbound_for(item, message_id="<once@client.test>")
    assert ingest(db, first) is Outcome.stored
    db.commit()
    assert ingest(db, inbound_for(item, message_id="<once@client.test>")) is Outcome.duplicate
    db.commit()
    assert len(stored(db)) == 1


def test_auto_replies_spam_and_empty_mail_are_ignored(db, inbound, item):
    assert ingest(db, inbound_for(item, Auto_Submitted="auto-replied")) is Outcome.ignored
    assert ingest(db, inbound_for(item, body="> only a quote\n")) is Outcome.ignored
    item.status = FeedbackStatus.spam
    assert ingest(db, inbound_for(item)) is Outcome.ignored
    assert stored(db) == []


@pytest.mark.parametrize("before", [FeedbackStatus.read, FeedbackStatus.archived])
def test_an_answer_brings_a_handled_item_back_to_unread(db, inbound, item, before):
    item.status = before
    db.commit()
    ingest(db, inbound_for(item))
    db.commit()
    assert db.get(Feedback, item.id).status is FeedbackStatus.new


def test_body_is_capped(db, inbound, item):
    ingest(db, inbound_for(item, body="x" * 9000))
    assert len(stored(db)[0].body) == 5000


def test_bounce_marks_the_outbound_reply_failed(db, inbound, item):
    sent = FeedbackReply(feedback_id=item.id, body="Hi", status="sent", message_id="<m-1@shop.test>")
    db.add(sent)
    db.commit()
    assert ingest(db, parse_message(dsn())) is Outcome.bounced
    db.commit()
    db.refresh(sent)
    assert (sent.status, sent.retryable, sent.error) == ("failed", False, "Bounced (5.1.1)")
    assert "no such user" not in str(sent.error)


def test_bounce_for_an_unknown_message_is_dropped(db, inbound, item):
    assert ingest(db, parse_message(dsn("other@x"))) is Outcome.unmatched


def test_customer_reply_event_goes_to_subscribed_webhooks_only_and_has_no_text(db, inbound, item):
    site = db.get(Site, item.site_id)
    hook, _ = make_webhook(db, site, events=["feedback.created", "feedback.customer_replied"])
    make_webhook(db, site, events=["feedback.created"])
    make_channel(db, site, events=["feedback.customer_replied"])  # email: the team is not mailed (yet)
    ingest(db, inbound_for(item, body="secret words"))
    db.commit()
    (row,) = db.scalars(select(NotificationOutbox)).all()
    assert row.channel_id == hook.id and row.event_type == "feedback.customer_replied"
    assert "secret words" not in str(row.payload) and row.payload["length"] == len("secret words")


# -- outbound Reply-To ---------------------------------------------------------------------------------


@pytest.fixture
def mailer(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setitem(providers._providers, "fake", provider)
    monkeypatch.setattr(settings, "mail_provider", "fake")
    return provider


def send(client, db, item):
    site = db.get(Site, item.site_id)
    h = as_role(client, db, site, Role.editor, "ed@example.com")
    r = client.post(f"/sites/{site.id}/feedback/{item.id}/replies", headers=h, json={"body": "On it."})
    assert r.status_code == 201, r.text


def test_replies_ask_the_customer_to_answer_the_shared_mailbox_when_inbound_is_on(
    client, db, item, mailer, inbound
):
    send(client, db, item)
    (sent,) = mailer.sent
    assert feedback_id_from_address(sent.reply_to) == item.id
    assert "ed@example.com" not in sent.text and "Shop team" in sent.text


def test_replies_still_go_to_the_editor_while_inbound_is_off(client, db, item, mailer, monkeypatch):
    monkeypatch.setattr(settings, "inbound_address", INBOX)  # an address alone is not enough: nobody reads it
    send(client, db, item)
    assert mailer.sent[0].reply_to == "ed@example.com"


# -- IMAP ---------------------------------------------------------------------------------------------


class FakeImap:
    def __init__(self, messages: dict[bytes, bytes]):
        self.messages, self.seen, self.closed = messages, set(), False

    def select(self, folder):
        self.folder = folder
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b" ".join(u for u in self.messages if u not in self.seen)]
        if command == "FETCH":
            uid, spec = args
            raw = self.messages[uid]
            if "SIZE" in spec:
                return "OK", [b"1 (UID %s RFC822.SIZE %d)" % (uid, len(raw))]
            return "OK", [(b"1 (BODY[] {%d}" % len(raw), raw), b")"]
        self.seen.add(args[0])  # STORE +FLAGS \Seen
        return "OK", []

    def logout(self):
        self.closed = True


@pytest.fixture
def server(monkeypatch, inbound):
    def install(messages):
        conn = FakeImap(messages)
        monkeypatch.setattr(imap, "_connect", lambda: conn)
        return conn

    return install


def test_imap_poll_stores_replies_and_marks_everything_seen(db, item, server):
    conn = server(
        {
            b"1": mail(to=reply_address(item.id), body="First"),
            b"2": mail(to=reply_address(item.id), Auto_Submitted="auto-replied"),
            b"3": b"\xff\xfe not an email",
        }
    )
    assert imap.ImapSource().poll(db) == 3  # every message was looked at; only the first one is an answer
    assert [r.body.strip() for r in stored(db)] == ["First"]
    assert conn.seen == {b"1", b"2", b"3"} and conn.closed


def test_a_message_that_cannot_be_read_is_skipped_not_retried_forever(db, server, monkeypatch):
    conn = server({b"1": b"whatever"})
    monkeypatch.setattr(imap, "parse_message", lambda raw: 1 / 0)
    assert imap.ImapSource().poll(db) == 0
    assert conn.seen == {b"1"}


def test_imap_skips_oversized_mail_without_downloading_it(db, item, server, monkeypatch):
    monkeypatch.setattr(settings, "inbound_max_bytes", 100)
    conn = server({b"1": mail(to=reply_address(item.id), body="x" * 500)})
    assert imap.ImapSource().poll(db) == 0
    assert stored(db) == [] and conn.seen == {b"1"}


def test_a_message_that_fails_to_store_stays_unread_for_the_next_pass(db, item, server, monkeypatch):
    conn = server({b"1": mail(to=reply_address(item.id))})
    monkeypatch.setattr(imap, "ingest", lambda *a: 1 / 0)
    assert imap.ImapSource().poll(db) == 0
    assert conn.seen == set() and conn.closed


@pytest.mark.parametrize(
    ("changes", "configured"),
    [
        ({}, True),
        ({"imap_host": ""}, False),
        ({"inbound_address": ""}, False),
        ({"imap_security": "none", "imap_username": "u"}, False),  # never a password in the clear
        ({"imap_security": "none"}, True),
    ],
)
def test_imap_needs_a_host_an_address_and_a_safe_login(inbound, monkeypatch, changes, configured):
    for name, value in changes.items():
        monkeypatch.setattr(settings, name, value)
    assert imap.ImapSource().is_configured() is configured


# -- registry and worker -------------------------------------------------------------------------------


def test_sources_register_by_import_scan_and_enable_inbound(inbound):
    registry.load_sources()
    assert isinstance(registry.get_source("imap"), PollingSource)
    assert registry.inbound_enabled() is True


def test_inbound_is_off_without_a_configured_source(monkeypatch):
    monkeypatch.setattr(settings, "inbound_address", INBOX)
    assert registry.inbound_enabled() is False


def test_worker_polls_on_a_timer_and_survives_a_failing_source(db, inbound, monkeypatch, caplog):
    from app import worker

    calls = []

    def boom(self, db):
        calls.append(1)
        raise RuntimeError("mailbox down")

    monkeypatch.setattr(imap.ImapSource, "poll", boom)
    monkeypatch.setattr(worker, "_last_inbound", float("-inf"))
    assert worker.poll_inbound(db) == 0
    assert worker.poll_inbound(db) == 0  # inside the interval: not asked again
    assert calls == [1] and "mailbox down" in caplog.text


def test_production_needs_an_address_when_imap_is_on():
    from pydantic import ValidationError

    from app.core.config import Settings

    base = {
        "environment": "production",
        "jwt_secret": "x" * 40,
        "totp_encryption_key": "k",
        "webhook_encryption_key": "k",
        "settings_encryption_key": "k",
    }
    with pytest.raises(ValidationError, match="INBOUND_ADDRESS"):
        Settings(_env_file=None, imap_host="imap.test", **base)
    assert Settings(_env_file=None, imap_host="imap.test", inbound_address=INBOX, **base).imap_host


def test_thread_tells_the_ui_when_answers_come_back(client, db, item, mailer, inbound):
    site = db.get(Site, item.site_id)
    h = as_role(client, db, site, Role.viewer, "v@example.com")
    thread = client.get(f"/sites/{site.id}/feedback/{item.id}/replies", headers=h).json()
    assert thread["inbound"] is True

"""Turn a raw RFC 822 email into an InboundMessage. Shared by every source that receives whole messages."""

import re
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser, Parser
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

from app.inbound.base import InboundMessage

_ID = re.compile(r"<([^<>\s]+)>")
# Headers that can carry the plus-address when the mail was delivered through an alias or a bcc.
_RECIPIENT_HEADERS = ("to", "cc", "delivered-to", "x-original-to", "envelope-to")
_AUTO_PRECEDENCE = {"bulk", "junk", "list", "auto_reply"}
_STATUS = re.compile(r"^\d\.\d{1,3}\.\d{1,3}$")


def normalize_id(value: str | None) -> str | None:
    """A Message-ID without its angle brackets, so ids compare the same however a client wrote them."""
    return value.strip().strip("<>").strip() or None if value else None


def _ids(value: str | None) -> list[str]:
    return [m for m in _ID.findall(value or "")]


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")


def _body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        parser = _Text()
        parser.feed(content)
        return "".join(parser.parts)
    return content


def _is_dsn(msg: EmailMessage) -> bool:
    return msg.get_content_type() == "multipart/report" and msg.get_param("report-type") == "delivery-status"


def _bounce_details(msg: EmailMessage) -> tuple[str | None, str | None]:
    """The id of the mail that bounced and its status code, from the delivery report's attached parts."""
    original = code = None
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "message/delivery-status":
            for block in part.get_payload():
                status = str(block.get("Status", "")).strip()
                if _STATUS.match(status):
                    code = code or status
        elif kind in {"message/rfc822", "text/rfc822-headers"}:
            payload = part.get_payload()
            headers: Message | None
            if isinstance(payload, list):
                headers = payload[0] if payload else None
            else:
                headers = Parser().parsestr(str(payload))
            if headers is not None and original is None:
                original = (_ids(str(headers.get("Message-ID", ""))) or [None])[0]
    return original, code


def _kind(msg: EmailMessage) -> str:
    if _is_dsn(msg):
        return "bounce"
    auto = str(msg.get("Auto-Submitted", "no")).strip().lower() != "no"
    precedence = str(msg.get("Precedence", "")).strip().lower() in _AUTO_PRECEDENCE
    robot = "X-Autoreply" in msg or "X-Autorespond" in msg
    null_path = str(msg.get("Return-Path", "")).strip() == "<>"
    return "auto" if auto or precedence or robot or null_path else "reply"


def parse_message(raw: bytes) -> InboundMessage:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    addresses = [a for h in _RECIPIENT_HEADERS for _, a in getaddresses([str(v) for v in msg.get_all(h, [])])]
    kind = _kind(msg)
    original, code = _bounce_details(msg) if kind == "bounce" else (None, None)
    return InboundMessage(
        sender=parseaddr(str(msg.get("From", "")))[1].lower(),
        recipients=[a.lower() for a in addresses if a],
        text="" if kind == "bounce" else _body_text(msg),
        message_id=normalize_id((_ids(str(msg.get("Message-ID", ""))) or [None])[0]),
        in_reply_to=normalize_id((_ids(str(msg.get("In-Reply-To", ""))) or [None])[0]),
        references=[i for i in _ids(str(msg.get("References", "")))],
        kind=kind,  # type: ignore[arg-type]
        bounced_message_id=normalize_id(original),
        bounce_code=code,
    )

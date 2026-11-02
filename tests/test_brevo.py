import json

import httpx
import pytest

from app.core.config import settings
from app.notifications import registry
from app.notifications.base import Message
from app.notifications.providers import brevo

KEY = "xkeysib-secret"


@pytest.fixture(autouse=True)
def _brevo_settings(monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", KEY)
    monkeypatch.setattr(settings, "notify_sender_email", "feedback@example.com")
    monkeypatch.setattr(settings, "notify_sender_name", "Ganymede")


def use_transport(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(brevo, "_transport", lambda: httpx.MockTransport(wrapped))
    return seen


def send(message: Message):
    provider = registry.get_provider("brevo")
    return provider.send(message, provider.ConfigModel())


def msg(**kw) -> Message:
    base = dict(to=["a@example.com"], subject="Hi", text="body", html="<p>body</p>")
    return Message(**{**base, **kw})


def test_registered_and_configuration_check(monkeypatch):
    provider = registry.get_provider("brevo")
    assert provider is not None and provider.is_configured()
    monkeypatch.setattr(settings, "brevo_api_key", "")
    assert not provider.is_configured()
    monkeypatch.setattr(settings, "brevo_api_key", KEY)
    monkeypatch.setattr(settings, "notify_sender_email", "")
    assert not provider.is_configured()


def test_request_shape_and_message_id(monkeypatch):
    seen = use_transport(monkeypatch, lambda r: httpx.Response(201, json={"messageId": "<abc@brevo>"}))

    result = send(msg(reply_to="user@example.com", tags=["feedback.created"]))

    assert (result.status, result.message_id) == ("sent", "<abc@brevo>")
    (request,) = seen
    assert str(request.url) == "https://api.brevo.com/v3/smtp/email"
    assert request.headers["api-key"] == KEY
    assert json.loads(request.content) == {
        "sender": {"email": "feedback@example.com", "name": "Ganymede"},
        "to": [{"email": "a@example.com"}],
        "subject": "Hi",
        "textContent": "body",
        "htmlContent": "<p>body</p>",
        "replyTo": {"email": "user@example.com"},
        "tags": ["feedback.created"],
    }


def test_optional_fields_are_omitted(monkeypatch):
    seen = use_transport(monkeypatch, lambda r: httpx.Response(201, json={"messageId": "1"}))
    send(msg(html=None))
    body = json.loads(seen[0].content)
    assert not {"htmlContent", "replyTo", "tags"} & body.keys()


def test_one_request_per_recipient(monkeypatch):
    ids = iter(["1", "2"])
    seen = use_transport(monkeypatch, lambda r: httpx.Response(201, json={"messageId": next(ids)}))

    result = send(msg(to=["a@example.com", "b@example.com"]))

    assert [json.loads(r.content)["to"] for r in seen] == [
        [{"email": "a@example.com"}],
        [{"email": "b@example.com"}],
    ]
    assert (result.status, result.message_id) == ("sent", "1,2")


@pytest.mark.parametrize(
    ("status", "outcome"),
    [(400, "failed"), (401, "failed"), (403, "failed"), (404, "failed"),
     (429, "retry"), (500, "retry"), (502, "retry"), (503, "retry")],
)
def test_status_mapping(monkeypatch, status, outcome):
    use_transport(monkeypatch, lambda r: httpx.Response(status, json={"code": "c", "message": "m"}))
    result = send(msg())
    assert result.status == outcome
    assert f"brevo {status}: c m" == result.error


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("t"), httpx.ConnectError("c"), httpx.ReadTimeout("r")])
def test_network_errors_are_retried(monkeypatch, exc):
    def boom(request):
        raise exc

    use_transport(monkeypatch, boom)
    result = send(msg())
    assert result.status == "retry"
    assert KEY not in result.error


def test_non_json_error_body(monkeypatch):
    use_transport(monkeypatch, lambda r: httpx.Response(502, text="<html>bad gateway</html>"))
    assert send(msg()).error == "brevo 502: "


def test_any_retryable_recipient_makes_the_whole_send_retry(monkeypatch):
    responses = iter([httpx.Response(201, json={"messageId": "1"}), httpx.Response(503, json={})])
    use_transport(monkeypatch, lambda r: next(responses))
    assert send(msg(to=["a@example.com", "b@example.com"])).status == "retry"


def test_permanent_failure_for_one_recipient_fails_the_send(monkeypatch):
    responses = iter([httpx.Response(201, json={"messageId": "1"}), httpx.Response(400, json={})])
    use_transport(monkeypatch, lambda r: next(responses))
    assert send(msg(to=["a@example.com", "b@example.com"])).status == "failed"

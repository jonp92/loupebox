import os

# Must be set before the app (and its settings) are imported.
# Set TEST_DATABASE_URL to run the suite on Postgres. It DROPS ALL TABLES in that database.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123"
os.environ["ADMIN_ORIGINS"] = '["http://admin.test"]'

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.origins import public_origins
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_engine, get_sessionmaker
from app.main import app
from app.models import Membership, Role, Site, User
from app.notifications.providers import brevo, smtp, webhook

SITE_ORIGIN = "https://shop.example.com"


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"a test tried to reach the network: {request.method} {request.url}")


_real_smtp_connect = smtp._connect


def _loopback_only_smtp():
    """Real SMTP only ever reaches a local fake server; anything else is a test bug."""
    if settings.smtp_host not in ("localhost", "127.0.0.1"):
        raise AssertionError(f"a test tried to open an SMTP connection to {settings.smtp_host!r}")
    return _real_smtp_connect()


@pytest.fixture(autouse=True)
def _isolated_from_dotenv(monkeypatch):
    """Settings also read the developer's real .env (Brevo key, PUBLIC_URL, ...). Tests must never see it,
    and no test may send real mail or webhooks: providers get a transport that fails loudly unless a test
    installs its own."""
    for name, value in (("brevo_api_key", ""), ("notify_sender_email", ""), ("public_url", ""), ("mail_provider", ""),
                        ("smtp_host", ""), ("smtp_username", ""), ("smtp_password", "")):
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(brevo, "_transport", lambda: httpx.MockTransport(_no_network))
    monkeypatch.setattr(webhook, "_transport", lambda: httpx.MockTransport(_no_network))
    monkeypatch.setattr(smtp, "_connect", _loopback_only_smtp)


@pytest.fixture(autouse=True)
def _clean_state():
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    limiter.reset()
    public_origins.invalidate()
    yield


@pytest.fixture
def client() -> TestClient:
    # Base URL carries the API prefix so tests can use short relative paths.
    return TestClient(app, base_url=f"http://testserver{settings.api_prefix}")


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


def make_user(db, email: str, *, superadmin: bool = False, password: str = "correct-horse-battery") -> User:
    user = User(email=email, password_hash=hash_password(password), is_superadmin=superadmin)
    db.add(user)
    db.commit()
    return user


def make_site(db, name: str = "Shop", origins: list[str] | None = None, **kw) -> Site:
    site = Site(
        name=name,
        public_key=f"pk_test_{name}",
        allowed_origins=origins if origins is not None else [SITE_ORIGIN],
        daily_limit=kw.pop("daily_limit", 1000),
        **kw,
    )
    db.add(site)
    db.commit()
    public_origins.invalidate()
    return site


def add_member(db, user: User, site: Site, role: Role) -> None:
    db.add(Membership(user_id=user.id, site_id=site.id, role=role))
    db.commit()


def login(client: TestClient, email: str, password: str = "correct-horse-battery") -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

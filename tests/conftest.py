import os

# Must be set before the app (and its settings) are imported.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123"
os.environ["ADMIN_ORIGINS"] = '["http://admin.test"]'

import pytest
from fastapi.testclient import TestClient

from app.core.origins import public_origins
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_engine, get_sessionmaker
from app.main import app
from app.models import Membership, Role, Site, User

SITE_ORIGIN = "https://shop.example.com"


@pytest.fixture(autouse=True)
def _clean_state():
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    limiter.reset()
    public_origins.invalidate()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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

from app.core.config import settings
from tests.conftest import make_user


def test_refresh_cookie_scoped_to_auth_routes(client, db):
    make_user(db, "a@example.com")
    r = client.post("/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery"})
    cookie = r.headers["set-cookie"]
    assert f"Path={settings.api_prefix}/auth" in cookie and "HttpOnly" in cookie
    assert settings.cookie_path == "/v1/api/auth"

    out = client.post("/auth/logout")
    assert f"Path={settings.api_prefix}/auth" in out.headers["set-cookie"]  # deletion must use the same path


def test_everything_lives_under_the_prefix(client, db):
    from fastapi.testclient import TestClient

    from app.main import app

    bare = TestClient(app)  # no prefix
    for path in ("/health", "/auth/me", "/sites", "/users", "/feedback", "/avatars/x"):
        assert bare.get(path).status_code == 404, path
    assert client.get("/health").status_code == 200

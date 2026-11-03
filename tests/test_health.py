import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get(f"{settings.api_prefix}/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_comes_from_the_version_file() -> None:
    body = client.get(f"{settings.api_prefix}/version").json()

    assert body["app_version"] == (Path(__file__).parents[1] / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", body["app_version"])

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get(f"{settings.api_prefix}/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

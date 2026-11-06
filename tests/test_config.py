import pytest
from pydantic import ValidationError

from app.core.config import Settings

KEYS = ("TOTP_ENCRYPTION_KEY", "WEBHOOK_ENCRYPTION_KEY", "SETTINGS_ENCRYPTION_KEY")
STRONG = "s" * 40


@pytest.fixture(autouse=True)
def _no_keys_from_env(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def make(**values) -> Settings:
    return Settings(_env_file=None, **values)  # never the developer's real .env


def test_production_needs_every_encryption_key():
    keys = {k.lower(): STRONG for k in KEYS}
    assert make(environment="production", jwt_secret=STRONG, **keys).environment == "production"
    for missing in KEYS:
        partial = {k: v for k, v in keys.items() if k != missing.lower()}
        with pytest.raises(ValidationError, match=missing):
            make(environment="production", jwt_secret=STRONG, **partial)


def test_production_names_all_missing_keys_at_once():
    with pytest.raises(ValidationError) as e:
        make(environment="production", jwt_secret=STRONG)
    assert all(k in str(e.value) for k in KEYS)


def test_production_still_needs_a_strong_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        make(environment="production", jwt_secret="short", **{k.lower(): STRONG for k in KEYS})


def test_development_falls_back_to_jwt_secret():
    assert make(environment="development").totp_encryption_key == ""

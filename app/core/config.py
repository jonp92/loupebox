from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Ganymede"
    app_version: str = "0.1.0"
    app_description: str = "A simple, open-source, self-hosted link submission and voting platform."

    environment: str = "development"
    database_url: str = "postgresql+psycopg://ganymede:ganymede@localhost:5432/ganymede"

    # Auth for the admin UI
    jwt_secret: str = _INSECURE_SECRET
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cookie_secure: bool = False
    # Use "none" (with cookie_secure) if the SPA is on a different *site* than the API.
    cookie_samesite: str = "lax"

    # Origins allowed to call the admin API (the SPA). Public /v1 origins are per-site.
    admin_origins: list[str] = ["http://localhost:5173"]

    # Only honour X-Forwarded-For when running behind a trusted reverse proxy.
    trust_proxy: bool = False

    # Public ingest hardening
    max_body_bytes: int = 16_384
    public_require_origin: bool = True
    public_ip_limit: int = 10  # submissions per IP per window
    public_key_limit: int = 120  # submissions per API key per window
    public_window_seconds: int = 60
    default_site_daily_limit: int = 1000
    dedupe_window_minutes: int = 10
    spam_link_threshold: int = 3  # messages with more links than this are quarantined

    # Profile avatar image size cap (bytes), stored in the DB and served from /avatars/{id}.
    avatar_max_bytes: int = 65_536

    # Login brute-force protection
    login_ip_limit: int = 20
    login_account_limit: int = 5
    login_window_seconds: int = 60

    @model_validator(mode="after")
    def _check_production_secret(self) -> "Settings":
        if self.environment == "production" and (
            self.jwt_secret == _INSECURE_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be set to a random value of 32+ chars in production")
        return self


settings = Settings()

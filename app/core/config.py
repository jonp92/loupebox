from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Ganymede"
    app_version: str = "0.1.0"
    app_description: str = "A simple, open-source, self-hosted link submission and voting platform."

    environment: str = "development"
    # Every route lives under this prefix, so a reverse proxy can send /v1/api/* to the API
    # and everything else to the web UI with no path rewriting.
    api_prefix: str = "/v1/api"
    database_url: str = "postgresql+psycopg://ganymede:ganymede@localhost:5432/ganymede"

    # Auth for the admin UI
    jwt_secret: str = _INSECURE_SECRET
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cookie_secure: bool = False
    # Use "none" (with cookie_secure) if the SPA is on a different *site* than the API.
    cookie_samesite: str = "lax"

    # Origins allowed to call the admin API (the SPA). Public ingest origins are per-site.
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

    # Public-ingest challenges (see app/challenges). Issuing is stateless, so these only bound abuse.
    challenge_ttl_seconds: int = 300
    challenge_ip_limit: int = 30  # challenge requests per IP per window
    challenge_key_limit: int = 600  # challenge requests per API key per window

    # Profile avatar image size cap (bytes), stored in the DB and served from {api_prefix}/avatars/{id}.
    avatar_max_bytes: int = 65_536

    # Notification worker (python -m app.worker)
    worker_poll_seconds: int = 5
    notify_hourly_cap: int = 5  # emails per channel per hour; the overflow is rolled into one summary
    notify_summary_delay_minutes: int = 15  # wait this long after the cap is hit before the summary
    notify_max_recipients: int = 20  # per channel
    notify_retention_days: int = 30  # finished (sent/failed) outbox rows are deleted after this
    # Brevo (email). Operator-owned, never stored in the database.
    brevo_api_key: str = ""
    notify_sender_email: str = ""
    notify_sender_name: str = "Ganymede"
    # Public origin of the admin UI, used for links in emails. Links are omitted when empty.
    public_url: str = ""

    # Audit log (admin actions). Events older than this are purged by the worker; 0 keeps them forever.
    audit_retention_days: int = 365

    # TOTP secrets are encrypted at rest with this key (any string; it is hashed into a Fernet key).
    # Falls back to JWT_SECRET, but then rotating JWT_SECRET locks TOTP users out: set it separately.
    totp_encryption_key: str = ""
    totp_issuer: str = "Ganymede"
    mfa_token_minutes: int = 5  # how long the password step stays valid while the code is entered
    mfa_hourly_limit: int = 20  # second-factor attempts per user per hour (the per-minute cap is login_account_limit)

    # Login brute-force protection
    login_ip_limit: int = 20
    login_account_limit: int = 5
    login_window_seconds: int = 60

    @property
    def cookie_path(self) -> str:
        """Refresh cookie is only sent to the auth routes."""
        return f"{self.api_prefix}/auth"

    @model_validator(mode="after")
    def _check_production_secret(self) -> "Settings":
        if self.environment == "production" and (
            self.jwt_secret == _INSECURE_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be set to a random value of 32+ chars in production")
        return self


settings = Settings()

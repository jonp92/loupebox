from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRET = "dev-insecure-change-me"
_ENCRYPTION_KEYS = ("totp_encryption_key", "webhook_encryption_key", "settings_encryption_key")


# The single source of the release version; the image build copies it next to app/.
VERSION = (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Loupebox"
    app_version: str = VERSION
    app_description: str = (
        "A self-hosted feedback inbox: collect, triage and answer feedback from your sites."
    )

    environment: str = "development"
    # Every route lives under this prefix, so a reverse proxy can send /v1/api/* to the API
    # and everything else to the web UI with no path rewriting.
    api_prefix: str = "/v1/api"
    database_url: str = "postgresql+psycopg://ganymede:ganymede@localhost:5432/ganymede"
    # Database connections one API process may open (pool size plus overflow) and how many seconds a request
    # waits for a free one before it fails.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    # Requests handled at once; 0 means as many as the database pool allows (pool size plus overflow). The
    # rest wait up to request_queue_seconds, then get a 503, so a burst slows the API down, not stops it.
    max_concurrent_requests: int = 0
    request_queue_seconds: int = 2

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

    # Shared rate limits for more than one API replica, e.g. redis://redis:6379/0. Empty: in-process.
    redis_url: str = ""

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
    notify_sender_name: str = "Loupebox"
    # Plain SMTP (email), operator-owned like Brevo. Sender is NOTIFY_SENDER_EMAIL / NOTIFY_SENDER_NAME.
    smtp_host: str = ""
    smtp_port: int = 587  # 587 with starttls, 465 with ssl, 25 or 1025 for a local relay with none
    smtp_username: str = ""
    smtp_password: str = ""
    # starttls: upgrade, and refuse to send if the server won't. ssl: TLS from the first byte.
    # none: no encryption at all; credentials are never sent that way (see providers/smtp.py).
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_timeout: int = 15
    # Public origin of the admin UI, used for links in emails. Links are omitted when empty.
    public_url: str = ""

    # Most items one bulk action (status change or delete) may touch.
    bulk_max_ids: int = 100

    # CSV export stops at this many rows per download.
    export_max_rows: int = 100_000

    # Webhook notifications. Targets must be public https hosts; turn this on to allow private,
    # loopback and plain-http targets (for a receiver on your own network).
    webhook_allow_private: bool = False

    # Audit log (admin actions). Events older than this are purged by the worker; 0 keeps them forever.
    audit_retention_days: int = 365

    # Secrets the server must read back are encrypted at rest, one key per purpose (any string). Required in
    # production. Elsewhere each falls back to JWT_SECRET, and rotating that would make them unreadable.
    totp_encryption_key: str = ""  # two-factor seeds
    webhook_encryption_key: str = ""  # webhook signing secrets
    settings_encryption_key: str = ""  # provider secrets set in the admin UI (System settings)
    totp_issuer: str = "Loupebox"
    mfa_token_minutes: int = 5  # how long the password step stays valid while the code is entered
    mfa_hourly_limit: int = (
        20  # second-factor attempts per user per hour (the per-minute cap is login_account_limit)
    )

    # Self-service password reset. It is offered only when PUBLIC_URL and a mail provider are configured.
    password_reset_minutes: int = 30  # how long an emailed link works
    password_reset_email_limit: int = 3  # requests per address per hour
    password_reset_ip_limit: int = 10  # requests per IP per hour
    # Which email provider sends account mail (password reset, replies). Empty: the first configured one.
    mail_provider: str = ""

    # Replies to the person who sent feedback.
    reply_max_per_item: int = 5  # sent replies per feedback item
    reply_site_hourly_limit: int = 30  # sends per site per hour, so one account cannot spray mail

    # Login brute-force protection
    login_ip_limit: int = 20
    login_account_limit: int = 5
    login_window_seconds: int = 60
    # Failed passwords per email from any IP, so guesses spread over many IPs still stop. Only
    # failures count, and a successful sign-in or password reset clears them.
    login_failure_limit: int = 10
    login_failure_window_seconds: int = 900

    @property
    def cookie_path(self) -> str:
        """Refresh cookie is only sent to the auth routes."""
        return f"{self.api_prefix}/auth"

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        if self.environment != "production":
            return self
        if self.jwt_secret == _INSECURE_SECRET or len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be set to a random value of 32+ chars in production")
        missing = [name.upper() for name in _ENCRYPTION_KEYS if not getattr(self, name)]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} must be set in production. Generate each with "
                '`python -c "import secrets; print(secrets.token_urlsafe(48))"` and keep it.'
            )
        return self


settings = Settings()

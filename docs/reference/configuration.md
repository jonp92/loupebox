# Settings (.env)

Loupebox reads its settings from environment variables, which Docker Compose takes from the `.env` file next
to `docker-compose.yml`. Change `.env`, then run `docker compose up -d` to apply it.

Many settings can also be changed by a superadmin on the **System** page, with no restart (see
[below](#changing-settings-in-the-app)).

The comments in [`.env.example`](https://github.com/jonp92/loupebox/blob/master/.env.example) explain every
setting, and `setup.sh` fills in the secrets for you.

## Required

| Setting | What it is |
|---|---|
| `JWT_SECRET` | Signs sign-in tokens. At least 32 characters. |
| `POSTGRES_PASSWORD` | Database password. Use letters, digits, `-`, `_` and `.` only. |
| `TOTP_ENCRYPTION_KEY` | Encrypts two-factor secrets. Set once and keep it. |
| `WEBHOOK_ENCRYPTION_KEY` | Encrypts webhook signing secrets. Set once and keep it. |
| `SETTINGS_ENCRYPTION_KEY` | Encrypts email passwords and keys saved on the System page. Set once and keep it. |

## Where things are

| Setting | Default | What it does |
|---|---|---|
| `ENVIRONMENT` | `production` in Docker | Use `development` locally to get `/v1/api/docs`. |
| `API_URL` | | The API's address as the browser sees it, with no path. |
| `ADMIN_ORIGINS` | the app on port 8080 | Addresses the admin app is served from. |
| `PUBLIC_URL` | | The admin app's address, used in emails. |
| `API_PORT`, `WEB_PORT`, `DB_PORT` | 8000, 8080, 5432 | Ports on the host. Always bound to localhost. |
| `LOUPEBOX_VERSION` | `latest` | Which image version to run. |

## Cookies and proxies

| Setting | What it does |
|---|---|
| `COOKIE_SECURE` | Set `true` when the admin app uses HTTPS. |
| `COOKIE_SAMESITE` | `lax` by default. Use `none` only if the app and API are on different sites. |
| `TRUST_PROXY` | Set `true` behind a reverse proxy so rate limits see real visitor addresses. |

## Email and alerts

| Setting | Default | What it does |
|---|---|---|
| `BREVO_API_KEY` | | See [Brevo](../notifications/brevo.md). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD` | | See [SMTP](../notifications/smtp.md). |
| `NOTIFY_SENDER_EMAIL`, `NOTIFY_SENDER_NAME` | | The From address and name. |
| `MAIL_PROVIDER` | first configured | `brevo` or `smtp`, for reset and reply email. |
| `NOTIFY_HOURLY_CAP` | 5 | Alerts per channel per hour. |
| `NOTIFY_RETENTION_DAYS` | 30 | How long sent and failed alerts are kept. |
| `PASSWORD_RESET_MINUTES` | 30 | How long a reset link works. |

## Limits and retention

| Setting | Default |
|---|---|
| `AUDIT_RETENTION_DAYS` | 365 (`0` keeps everything) |
| `BULK_MAX_IDS` | 100 |
| `EXPORT_MAX_ROWS` | 100,000 |
| `REPLY_MAX_PER_ITEM` | 5 |
| `REPLY_SITE_HOURLY_LIMIT` | 30 |
| `AVATAR_MAX_BYTES` | 65,536 |
| `PASSWORD_RESET_EMAIL_LIMIT`, `PASSWORD_RESET_IP_LIMIT` | 3 and 10 per hour |
| `LOGIN_ACCOUNT_LIMIT` | 5 sign-in attempts per minute |
| `LOGIN_FAILURE_LIMIT`, `LOGIN_FAILURE_WINDOW_SECONDS` | 10 wrong passwords per email per 15 minutes, from any IP. A successful sign-in or password reset clears them. |
| `MFA_HOURLY_LIMIT` | 20 two-factor attempts per hour |

## Changing settings in the app

Superadmins can change email, notification, rate-limit, sign-in and retention settings on the **System** page.
A value saved there:

* **wins over `.env`**. Editing `.env` does not change a setting that was saved on the System page. Each field
  says where its value comes from, and **Reset** goes back to the `.env` value.
* **takes effect without a restart**, in the API at once and in the worker within one poll interval.
* **is recorded in the audit log** with its old and new value.

The SMTP password and the Brevo API key can be set there but never read back: they are stored encrypted with
`SETTINGS_ENCRYPTION_KEY`, and the page only shows whether they are set. If that key changes, saved
credentials can't be read any more and Loupebox falls back to the `.env` values until they are entered again.

Settings that are read at startup or that weaken a security check (cookies, proxies, origins, private webhook
targets, request size) are shown on the page but can only be changed in `.env`.

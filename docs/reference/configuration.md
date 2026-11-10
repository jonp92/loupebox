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
| `REDIS_URL` | Empty by default. Set it, for example to `redis://redis:6379/0`, to run more than one API container. See [More than one API container](../install/production.md#more-than-one-api-container). |

## Email and alerts

| Setting | Default | What it does |
|---|---|---|
| `BREVO_API_KEY` | | See [Brevo](../notifications/brevo.md). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD` | | See [SMTP](../notifications/smtp.md). |
| `INBOUND_ADDRESS`, `IMAP_HOST`, `IMAP_PORT`, `IMAP_SECURITY`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `IMAP_POLL_SECONDS` | | See [Answers by email](../manage/inbound-email.md). |
| `INBOUND_MAX_BYTES` | 262144 | Incoming mail larger than this is skipped. |
| `NOTIFY_SENDER_EMAIL`, `NOTIFY_SENDER_NAME` | | The From address and name. |
| `MAIL_PROVIDER` | first configured | `brevo` or `smtp`, for reset and reply email. |
| `NOTIFY_HOURLY_CAP` | 5 | Alerts per channel per hour. |
| `NOTIFY_RETENTION_DAYS` | 30 | How long sent and failed alerts are kept. |
| `PASSWORD_RESET_MINUTES` | 30 | How long a reset link works. |

## Images

See [Images with feedback](../manage/images.md). Each site also turns them on in its own settings.

| Setting | Default | Meaning |
|---|---|---|
| `ATTACHMENT_MAX_COUNT` | 3 | Images per submission |
| `ATTACHMENT_MAX_BYTES` | 5242880 | Largest uploaded file, in bytes |
| `ATTACHMENT_MAX_EDGE` | 2048 | Longer side in pixels; larger images are scaled down |
| `ATTACHMENT_MAX_PIXELS` | 20000000 | Larger pictures are refused before they are decoded |
| `STORAGE_BACKEND` | `local` | Where files go. Only `local` for now |
| `ATTACHMENTS_DIR` | `data/attachments` (`/data/attachments` in the image) | The folder for `local`; also editable under System → Image storage. The API and the worker must share it |

Restart the API after changing these.

Where the files go is chosen in the admin app (System → Image storage), or here. See
[Image storage](../install/image-storage.md).

| Setting | Default | Meaning |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `S3_ENDPOINT_URL` | empty | Empty for Amazon S3; the provider's S3 address otherwise |
| `S3_REGION` | empty | Empty means `us-east-1`; Cloudflare R2 uses `auto` |
| `S3_BUCKET` | empty | The bucket name |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | empty | The access key (the secret is write-only in the admin app) |
| `S3_PATH_STYLE` | `false` | `true` for MinIO and most self-hosted servers |
| `S3_PREFIX` | empty | A folder inside the bucket |

## Limits and retention

| Setting | Default |
|---|---|
| `AUDIT_RETENTION_DAYS` | 365 (`0` keeps everything) |
| `BULK_MAX_IDS` | 100 |
| `EXPORT_MAX_ROWS` | 100,000 |
| `PERSON_EXPORT_MAX_BYTES` | 524,288,000 (the personal-data zip stops adding pictures past this) |
| `REPLY_MAX_PER_ITEM` | 5 |
| `REPLY_SITE_HOURLY_LIMIT` | 30 |
| `AVATAR_MAX_BYTES` | 65,536 |
| `PASSWORD_RESET_EMAIL_LIMIT`, `PASSWORD_RESET_IP_LIMIT` | 3 and 10 per hour |
| `LOGIN_ACCOUNT_LIMIT` | 5 sign-in attempts per minute |
| `PASSWORD_MIN_LENGTH` | 12 (shortest allowed when a password is next set; minimum 8) |
| `REQUIRE_TOTP` | false ([everyone must use 2FA](../security/two-factor.md#requiring-2fa-for-everyone)) |
| `LOGIN_FAILURE_LIMIT`, `LOGIN_FAILURE_WINDOW_SECONDS` | 10 wrong passwords per email per 15 minutes, from any IP. A successful sign-in or password reset clears them. |
| `MFA_HOURLY_LIMIT` | 20 two-factor attempts per hour |

## Busy servers

The API keeps a small pool of database connections and handles only as many requests at once as the pool can
serve. During a burst the extra requests wait a moment; if no slot frees up they get a `503` with a
`Retry-After` header, and the API keeps working. These settings change that:

| Setting | Default | What it does |
|---|---|---|
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | 5 and 10 | Database connections one API container may open (15 at most). |
| `DB_POOL_TIMEOUT` | 30 | Seconds a request waits for a free connection before it fails. |
| `MAX_CONCURRENT_REQUESTS` | `0` | Requests handled at once. `0` means pool size plus overflow. |
| `REQUEST_QUEUE_SECONDS` | 2 | How long an extra request waits for a slot before the `503`. |

Each API container opens its own connections, so add them up if you run several. Postgres allows 100
connections by default.

## Changing settings in the app

The **Status** tab shows whether the database, worker, outbox and Redis (if used) are healthy. If the worker
shows as down, nothing is sent: start `python -m app.worker`. The **Email & notifications** tab can send a
test email to you through each email provider.

The search box at the top of the System page (press `/` to reach it) finds a setting by its name, help text or
`.env` key across all tabs and takes you to it. The buttons under it show only settings changed in the UI, secrets
that are not set yet, or settings that only `.env` can change.

Superadmins can change email, notification, rate-limit, sign-in and retention settings on the **System** page.
A value saved there:

* **wins over `.env`**. Editing `.env` does not change a setting that was saved on the System page. Each field
  says where its value comes from, and **Reset** goes back to the `.env` value.
* **takes effect without a restart**: at once in the API container that saved it, within 30 seconds in any
  other API containers, and in the worker within one poll interval.
* **is recorded in the audit log** with its old and new value.

The SMTP password and the Brevo API key can be set there but never read back: they are stored encrypted with
`SETTINGS_ENCRYPTION_KEY`, and the page only shows whether they are set. If that key changes, saved
credentials can't be read any more and Loupebox falls back to the `.env` values until they are entered again.

Settings that are read at startup or that weaken a security check (cookies, proxies, origins, private webhook
targets, request size) are shown on the page but can only be changed in `.env`.

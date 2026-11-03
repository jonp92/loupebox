# Ganymede: form feedback server

FastAPI + Postgres API with a React admin UI (`web/`). Static sites post feedback with a public
site key; staff review it in the UI under per-site roles.

## Run with Docker

```bash
./scripts/setup.sh       # writes .env with generated secrets (needs openssl)
docker compose up -d --build
docker compose run --rm api python -m scripts.create_superadmin you@example.com
```

Then open http://localhost:8080 and sign in. Prerequisites: Docker with the compose plugin. To
set the secrets by hand instead, `cp .env.example .env` and fill in the blanks (see the comments inside).

* Web UI: http://localhost:8080 · API: http://localhost:8000/v1/api (interactive docs at `/v1/api/docs` only when
  `ENVIRONMENT` is not `production`; compose defaults to production, set `ENVIRONMENT=development` locally)
* Host ports are bound to localhost only; use a reverse proxy for anything public. Override them
  with `API_PORT`, `WEB_PORT` and `DB_PORT` in `.env` (defaults 8000 / 8080 / 5432).
* Services: `db` (Postgres), `migrate` (one-shot `alembic upgrade head`, the API waits for it),
  `api`, `worker` (sends notification emails), `web` (static build served by nginx, non-root).
* The web image reads `API_URL` at container start, so one image works in any environment.
  `ADMIN_ORIGINS` (API side) must include the origin the UI is served from.
* For a public deployment see **Deploy behind Caddy** below; the containers speak plain HTTP.
* Keep the API at **one replica/worker** until rate limiting is moved to Redis (see below).
* Data lives in the `pgdata` volume. Back it up; `docker compose down -v` deletes it.

## Run locally (without Docker for the app)

```bash
./scripts/setup.sh && docker compose up -d db   # .env with secrets, then Postgres only
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m scripts.create_superadmin you@example.com
uvicorn app.main:app --reload          # http://127.0.0.1:8000/docs

cd web && cp .env.example .env && npm install && npm run dev   # http://localhost:5173
```

Tests run on in-memory SQLite by default: `pytest`. To run them on Postgres, point
`TEST_DATABASE_URL` at a **throwaway** database (the suite drops all its tables).

## Notifications

Per-site email alerts for new feedback, sent through Brevo or any SMTP server. Admins configure channels in the UI
(site, **Notifications** tab). The API only queues rows in an outbox table; the `worker` service
(`python -m app.worker`) delivers them with retries, so nothing sends without it running.

* Set `BREVO_API_KEY` and `NOTIFY_SENDER_EMAIL` in `.env`; the provider shows as disabled in the UI
  until both are set. Setup steps: [docs/BREVO_SETUP.md](docs/BREVO_SETUP.md). To use a plain SMTP
  server instead, set `SMTP_HOST` (plus port, security and credentials) and `NOTIFY_SENDER_EMAIL`:
  [docs/SMTP_SETUP.md](docs/SMTP_SETUP.md). TLS is verified and never silently dropped.
* `PUBLIC_URL` (admin UI origin) adds links to emails. `NOTIFY_HOURLY_CAP` (default 5) limits emails
  per channel per hour; the overflow is rolled into one summary email.
* Locally, run the worker next to the API with the same `.env`: `python -m app.worker`.
* Sent and failed outbox rows are deleted after 30 days (`NOTIFY_RETENTION_DAYS`).
* Design and decisions: [docs/NOTIFICATIONS_PLAN.md](docs/NOTIFICATIONS_PLAN.md).

## Audit log

Superadmins see every administrative change under **Audit** in the top bar: who did what, when, and
on which site. Recorded: user create/update/promote/demote/enable/disable/password reset/avatar,
site create/update/key rotation/delete, member add/role change/remove, notification channel
create/update/delete, feedback deletion, and people changing their own password (or resetting it by email) or two-factor settings
(including sign-ins with a recovery code), webhook secret rotation and CSV exports.

* Each event is written in the same transaction as the change, so a change that fails leaves no
  event, and an event never exists for a change that did not happen. Actor email, site name and a
  plain-English summary are stored as they were at the time, so history stays readable after renames
  and site deletions.
* Never recorded: passwords, API keys, notification settings and recipient addresses (only that they
  changed) and the text of feedback or notes. Triage status changes and logins are not logged; assignment, tag
  and note-deletion changes are (ids and tag names only).
* The worker deletes events older than `AUDIT_RETENTION_DAYS` (default 365; `0` keeps everything).
* The log is append-only through the API, but a database admin can still edit the table: ship it
  elsewhere if you need tamper evidence.

## Model

* **Site**: a client website with a public key (`pk_...`) and an origin allow-list.
* **Roles** (per site): `viewer` reads (feedback, tags, assignee, notes), `editor` triages (status, assignee, tags, notes), `admin` deletes feedback and
  manages settings, key and members. `superadmin` is global: creates sites/users, admin everywhere.
* Non-members get 404 for sites they can't see.

## Deploy behind Caddy (feedback.pressler.tech)

Every API route lives under `/v1/api` (`API_PREFIX`), so Caddy needs one rule: `/v1/api/*` goes to
the API, everything else to the web UI. No path rewriting. UI and API share an origin, so the admin
UI needs no CORS, and client sites post to `https://feedback.pressler.tech/v1/api/feedback`.

1. DNS: point `feedback.pressler.tech` at the machine. Caddy gets the certificate automatically.
2. `cp deploy/production.env.example .env` and fill in `JWT_SECRET` and `POSTGRES_PASSWORD`.
3. `docker compose up -d --build`, then create the first admin:
   `docker compose run --rm api python -m scripts.create_superadmin you@pressler.tech`
4. Add [deploy/Caddyfile](deploy/Caddyfile) to the host's Caddyfile and `caddy reload`. It proxies
   to `127.0.0.1:8000` (API) and `127.0.0.1:8080` (UI), which compose binds to localhost only, so
   nothing is reachable except through Caddy. If you change `API_PORT` / `WEB_PORT` in `.env`,
   change the Caddyfile upstreams to match.
5. In the admin UI create a site and list the client site's origins. Give clients
   `https://feedback.pressler.tech/v1/api` as their API URL.

Notes:

* `TRUST_PROXY=true` makes rate limits use the client IP from `X-Forwarded-For`. Caddy replaces any
  client-supplied value, but that is only safe while the API port is unreachable except through
  Caddy; never expose it publicly with this on.
* `/health` is `/v1/api/health` (the container health check uses it). Interactive docs
  (`/v1/api/docs`) exist only when `ENVIRONMENT` is not `production`.
* If Caddy runs in a container, join it to the compose network and proxy to `api:8000` / `web:8080`.

## Mobile and PWA

The admin UI is an installable single-page app (add to home screen / install from the browser):

* `web/public/manifest.webmanifest` (standalone display, indigo splash, 192/512 and maskable icons)
  and `web/public/sw.js`, registered in production builds only.
* The service worker caches the app shell, hashed assets and icons so the UI opens offline. It
  never touches the API, `/config.js` or non-GET requests, so no API data or auth ends up cached.
  Offline, the shell loads but data screens need the network.
* Updating: a new deploy is picked up on the next navigation (the shell is fetched network-first).
  Bump `VERSION` in `sw.js` if you ever need to drop all cached assets.
* App-style touch: double-tap zoom is disabled with `touch-action: manipulation` and inputs are 16px
  on touch devices so iOS doesn't zoom on focus. Pinch zoom is intentionally left on (accessibility).
  To lock it fully, add `maximum-scale=1` to the viewport meta in `web/index.html` (Android honors it;
  iOS ignores it).
* The browser/status-bar color follows the active theme (`src/theme.ts`).

## Public API

`POST /v1/api/feedback` with header `X-API-Key`. See [examples/static-site.html](examples/static-site.html).
Fields: `message` (required), `rating` 1-5, `name`, `email`, `page_url`, `metadata`, `website` (honeypot).

### Abuse mitigations

| Layer | What it does |
|---|---|
| Origin allow-list | Request `Origin` must be on the site's list (no wildcards); missing Origin rejected. Preflight/CORS use the union of active sites' origins, the route enforces the exact list. |
| Rate limits | Per IP (before parsing/DB work) and per key, `429` + `Retry-After`. Login is limited per IP and per IP+email. |
| Daily quota | Per-site cap on submissions per UTC day. |
| Body/field limits | 16 KB body cap (also for chunked), strict schema (unknown fields rejected), length caps, NUL stripping, `http(s)` only `page_url`. |
| Honeypot | Filled `website` field returns a fake success and stores nothing. |
| Dedupe | Identical message+email within 10 min returns the original receipt. |
| Quarantine | Messages with many links are stored as `spam` and hidden by default. |
| Key rotation / disable | Rotate the key or deactivate a site instantly. Same 403 for every key failure. |
| Privacy | IPs stored only as keyed hashes. |

Each site's **Activity** tab (all roles) shows what the defenses are doing: stored vs quarantined
vs blocked submissions per day, with a table view. Dropped submissions (honeypot, wrong origin,
per-key rate limit, daily cap, failed challenges, duplicates) are counted per site per UTC day in `site_stats`;
quarantined spam is counted from feedback. Attempts with an unknown key can't be attributed to
a site and aren't counted.

The admin UI renders all feedback as text (never HTML) and only links `http(s)` URLs.

## Profiles

Users have a first and last name and an optional avatar. Only superadmins can edit names and
emails (`PATCH /v1/api/users/{id}`). Users manage their own avatar and password:

* `PUT /v1/api/auth/me/avatar`: raw image body with `Content-Type` image/png, image/jpeg or image/webp
  (content-sniffed; SVG rejected), max `AVATAR_MAX_BYTES` (64 KB). `DELETE /v1/api/auth/me/avatar` removes it.
* `GET /v1/api/avatars/{user_id}`: serves the image. Unauthenticated so a plain `<img>` works; ids are
  random UUIDs and nothing else is exposed. API responses carry `avatar_url` (`/v1/api/avatars/{id}?v=...`),
  and the `v` changes on upload so browsers cache it forever.
* `POST /v1/api/auth/me/password`: requires the current password and signs out all other sessions.

The UI crops and resizes uploads to 256x256 before sending.

## Feedback widget

An embeddable, customizable feedback widget ships with the web app as an ES module, no build step needed on
the site that uses it:

```html
<script type="module">
  import { createWidget } from "https://your-ganymede/widget/v1/ganymede.js";
  createWidget({ url: "https://your-ganymede/v1/api", key: "pk_..." });
</script>
```

Visitors can tag feedback with issue-type badges (bug, idea, question, praise, or your own), which arrive as
`metadata.issue_type`, show as a badge and a filter in the admin UI, and appear in the CSV export, notification
emails and webhooks. The snippet with your key filled in is under **Site → Settings → Feedback widget**; every
option, theming and the upgrade policy are in [docs/WIDGET.md](docs/WIDGET.md). A runnable page is in
`examples/widget.html`.

## Filtering and bulk actions

The feedback list filters by status, search text, issue type, rating, whether an email was given, and a
date range (`GET /v1/api/sites/{id}/feedback?status=&q=&issue_type=&rating=&has_email=&created_from=&created_to=`;
dates are inclusive UTC days, `YYYY-MM-DD`). Tick items (or "Select all on this page") to change their status or
delete them in one go: `POST /v1/api/sites/{id}/feedback/bulk` with `{"ids": [...], "action": "set_status",
"status": "archived"}` or `{"ids": [...], "action": "delete"}`. Editors may change status, only admins may delete,
as for a single item. Ids from other sites are skipped, at most `BULK_MAX_IDS` (100) per request, and a bulk
delete is one audit event (ids and count, never the messages).

## Assignee, tags and notes

* **Assignee**: any editor or admin of the site (viewers and non-members cannot hold one; losing editor access
  clears the assignment). The list has "Assigned to me" / "Unassigned" tabs with counts, a per-person filter,
  and the dashboard lists your open assigned items across sites. Double-click the assignee on a card,
  right-click (or long-press, or the "⋯" button) for quick actions, or tick items and use "Assign to…".
  People are found by searching (`GET .../feedback/assignees?q=`, at most 20 results, editors only), never
  listed in full, so large sites work; the menu offers "Me" and your recent picks.
* **Tags**: per-site free text, stored as lower-case slugs (`needs-review`), up to 10 per item. Filter with
  `?tag=`; `GET .../feedback/tags` lists them with counts. `?assignee=<user id>|none` filters by assignee.
* **Notes**: internal, never shown to the submitter or included in exports. Everyone on the site can read them,
  editors add them, an author deletes their own and an admin any. The list shows a note count; the notes
  themselves are on the item's page (`/sites/{id}/feedback/{feedback_id}`).
* Bulk (`POST .../feedback/bulk`) also takes `assign` (`assignee_id`, omit to unassign), `add_tag` and
  `remove_tag` (`tag`); `PATCH .../feedback/{id}` takes any of `status`, `assignee_id` and `tags`. The CSV
  export has `tags` and `assignee` (email) columns.

## Replying to the person who sent feedback

When a feedback item has an email address, editors can answer it from the item's page. The reply is emailed
through the mail provider (`MAIL_PROVIDER`, the same one that sends password resets) with the original quoted
and **Reply-To set to the editor**, so the person's answer lands in that editor's own inbox.

* Sent synchronously, not through the outbox, so reply text is not queued for days. The result is on the
  reply: `sent` means the mail server accepted it (not that it was delivered); `failed` shows the server's
  reason. A temporary failure (`retryable`) has a "Try again" button; a refused recipient does not.
* Limits: `REPLY_MAX_PER_ITEM` (5) sent replies per item and `REPLY_SITE_HOURLY_LIMIT` (30) sends per site per
  hour. Spam items and items without an address cannot be replied to. Viewers can read the thread; editors send.
* The audit log records the reply id, outcome and length, never the text or the address. The address stays on
  the feedback item and is shown masked in the UI.
* Webhook channels can subscribe to `feedback.replied` (ids and length only, no reply text). Email channels
  never get it.
* **Scope:** Ganymede is an inbox for feedback on small tools, not a ticketing system: there are no SLAs,
  ticket statuses or queues, and none are planned. To use a helpdesk, send feedback to it with a webhook.
  Replies from the submitter are not read yet (outbound only); the `feedback_replies` table already has
  `direction`, `source` and `in_reply_to` columns for that.

## Exporting feedback

**Export CSV** on a site's feedback list downloads what the filters show
(`GET /v1/api/sites/{id}/feedback/export.csv`, same query parameters as the list, any role that can view the site). Columns:
id, created_at (UTC), status, issue_type, rating, name, email, message, page_url, meta. Text that a spreadsheet
would run as a formula (starting with `=`, `+`, `-` or `@`) is prefixed with an apostrophe. Downloads
stop at `EXPORT_MAX_ROWS` (100,000). Each export is recorded in the audit log (who, how many rows, never
the contents).

## Webhooks

Besides email, a site can POST each new feedback item to a URL as signed JSON, with retries, SSRF
protection and a per-channel secret. See [docs/WEBHOOKS.md](docs/WEBHOOKS.md).

## Auth

Login returns a 15 min access token (kept in memory by the SPA) and sets a rotating, httpOnly
refresh cookie (path `/auth`). Replaying a rotated refresh token revokes all of the user's
sessions. Passwords use argon2. Admin CORS is limited to `ADMIN_ORIGINS`.

### Forgot password

The login page offers **Forgot password?** when the server can send the email: `PUBLIC_URL` is set (it
builds the link) and an email provider is configured (Brevo or SMTP). Otherwise the link is hidden and
`POST /v1/api/auth/password-reset/request` answers 404, and a superadmin resets the password on the
Users page instead.

* The email links to `{PUBLIC_URL}/reset-password#token=...`. The token is in the URL fragment, so it
  never reaches server logs or Referer headers, and the page removes it from the address bar.
* Links work once and expire after `PASSWORD_RESET_MINUTES` (default 30). A newer request replaces older
  links. Only a hash of the token is stored.
* Requests always answer `202` with the same text and send after responding, so neither the response nor
  its timing shows whether an address has an account. Limits: `PASSWORD_RESET_EMAIL_LIMIT` (3) per
  address and `PASSWORD_RESET_IP_LIMIT` (10) per IP, per hour. These also bound how much of your email
  provider's daily quota a stranger can use.
* Using a link changes the password, signs the user out everywhere and emails them that it happened. It
  does not log them in, and it does **not** turn off two-factor: they still need their code.
* The email goes straight out, without the notification outbox (which would keep a live token for
  `NOTIFY_RETENTION_DAYS`). So there are no retries: if sending fails it is logged and the user asks again.
  `MAIL_PROVIDER` picks the provider (default: the first configured one).

### Two-factor authentication (TOTP)

Any user can turn on an authenticator-app code (RFC 6238) under **Profile**. It is optional and
per user; nothing changes for people who don't enable it.

* Setup shows a QR code and the text key, and only takes effect once a code is confirmed. It then
  shows 10 one-time recovery codes (once; only their hashes are stored).
* Sign-in becomes two steps: `POST /v1/api/auth/login` returns `{"mfa_required": true, "mfa_token"}`
  instead of tokens, and `POST /v1/api/auth/login/totp` with that token (valid 5 minutes, useless
  as an access token) and a code opens the session. A code works once, and attempts are rate limited
  per user, separately for sign-in and for managing the setting (`LOGIN_ACCOUNT_LIMIT` per minute,
  `MFA_HOURLY_LIMIT` per hour).
* Turning it off or replacing the recovery codes needs the password and a current code. Enabling or
  disabling signs out the other sessions.
* Secrets are encrypted in the database with `TOTP_ENCRYPTION_KEY` (falls back to `JWT_SECRET`;
  set it separately so rotating `JWT_SECRET` doesn't lock people out).
* Lockout recovery: a superadmin can use **Reset 2FA** on the Users page (`DELETE /v1/api/users/{id}/totp`),
  or run `python -m scripts.reset_totp user@example.com` on the server. Both sign the user out
  everywhere and are the only way back in without a code or recovery code.

## Production notes

* Set `ENVIRONMENT=production`, a 32+ char `JWT_SECRET`, `COOKIE_SECURE=true`. If the SPA is on a
  different *site* than the API, also `COOKIE_SAMESITE=none`.
* Behind a reverse proxy set `TRUST_PROXY=true` and make sure the proxy overwrites `X-Forwarded-For`.
* Rate limiting is in-process: with multiple workers/instances the limits multiply. Replace
  `app/core/rate_limit.py` with a Redis-backed implementation of the same `hit()` interface.
* A public key can't stop a determined non-browser attacker (anyone can forge `Origin` from a script).
  Rate limits, quotas, honeypot and quarantine are what contain that. For stronger protection turn on a
  per-site **challenge** (Site → Settings → Bot protection): a signed, single-use proof-of-work the form
  has to solve, see `docs/CLIENT_INTEGRATION.md`. Challenges are pluggable: add a module under
  `app/challenges/verifiers/` that registers a `ChallengeVerifier` (for example a Turnstile/hCaptcha check).

## License

Copyright 2026 Jonathan L. Pressler. Ganymede is licensed under the [GNU AGPL-3.0](LICENSE). The embeddable widget (`web/widget/`) is
licensed under [Apache-2.0](web/widget/LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md) for the
sign-off (DCO) required on contributions.

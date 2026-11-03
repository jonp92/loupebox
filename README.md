# Ganymede: form feedback server

FastAPI + Postgres API with a React admin UI (`web/`). Static sites post feedback with a public
site key; staff review it in the UI under per-site roles.

## Run with Docker

```bash
cp .env.example .env     # set JWT_SECRET and POSTGRES_PASSWORD (see comments inside)
docker compose up -d --build
docker compose run --rm api python -m scripts.create_superadmin you@example.com
```

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
docker compose up -d db                # Postgres only (needs POSTGRES_PASSWORD in .env)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                   # set JWT_SECRET and DATABASE_URL
alembic upgrade head
python -m scripts.create_superadmin you@example.com
uvicorn app.main:app --reload          # http://127.0.0.1:8000/docs

cd web && cp .env.example .env && npm install && npm run dev   # http://localhost:5173
```

Tests run on in-memory SQLite by default: `pytest`. To run them on Postgres, point
`TEST_DATABASE_URL` at a **throwaway** database (the suite drops all its tables).

## Notifications

Per-site email alerts for new feedback, sent through Brevo. Admins configure channels in the UI
(site, **Notifications** tab). The API only queues rows in an outbox table; the `worker` service
(`python -m app.worker`) delivers them with retries, so nothing sends without it running.

* Set `BREVO_API_KEY` and `NOTIFY_SENDER_EMAIL` in `.env`; the provider shows as disabled in the UI
  until both are set. Setup steps: [docs/BREVO_SETUP.md](docs/BREVO_SETUP.md).
* `PUBLIC_URL` (admin UI origin) adds links to emails. `NOTIFY_HOURLY_CAP` (default 5) limits emails
  per channel per hour; the overflow is rolled into one summary email.
* Locally, run the worker next to the API with the same `.env`: `python -m app.worker`.
* Sent and failed outbox rows are deleted after 30 days (`NOTIFY_RETENTION_DAYS`).
* Design and decisions: [docs/NOTIFICATIONS_PLAN.md](docs/NOTIFICATIONS_PLAN.md).

## Audit log

Superadmins see every administrative change under **Audit** in the top bar: who did what, when, and
on which site. Recorded: user create/update/promote/demote/enable/disable/password reset/avatar,
site create/update/key rotation/delete, member add/role change/remove, notification channel
create/update/delete, feedback deletion, and people changing their own password.

* Each event is written in the same transaction as the change, so a change that fails leaves no
  event, and an event never exists for a change that did not happen. Actor email, site name and a
  plain-English summary are stored as they were at the time, so history stays readable after renames
  and site deletions.
* Never recorded: passwords, API keys, notification settings and recipient addresses (only that they
  changed) and the text of feedback. Triage status changes and logins are not logged.
* The worker deletes events older than `AUDIT_RETENTION_DAYS` (default 365; `0` keeps everything).
* The log is append-only through the API, but a database admin can still edit the table: ship it
  elsewhere if you need tamper evidence.

## Model

* **Site**: a client website with a public key (`pk_...`) and an origin allow-list.
* **Roles** (per site): `viewer` reads, `editor` triages (status), `admin` deletes feedback and
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

## Auth

Login returns a 15 min access token (kept in memory by the SPA) and sets a rotating, httpOnly
refresh cookie (path `/auth`). Replaying a rotated refresh token revokes all of the user's
sessions. Passwords use argon2. Admin CORS is limited to `ADMIN_ORIGINS`.

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

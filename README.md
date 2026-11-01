# Ganymede: form feedback server

FastAPI + Postgres API with a React admin UI (`web/`). Static sites post feedback with a public
site key; staff review it in the UI under per-site roles.

## Run locally

```bash
docker compose up -d db                # Postgres
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                   # set JWT_SECRET
alembic upgrade head
python -m scripts.create_superadmin you@example.com
uvicorn app.main:app --reload          # http://127.0.0.1:8000/docs

cd web && cp .env.example .env && npm install && npm run dev   # http://localhost:5173
```

Tests (SQLite in memory, no Postgres needed): `pytest`

## Model

* **Site**: a client website with a public key (`pk_...`) and an origin allow-list.
* **Roles** (per site): `viewer` reads, `editor` triages (status), `admin` deletes feedback and
  manages settings, key and members. `superadmin` is global: creates sites/users, admin everywhere.
* Non-members get 404 for sites they can't see.

## Public API

`POST /v1/feedback` with header `X-API-Key`. See [examples/static-site.html](examples/static-site.html).
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
per-key rate limit, daily cap, duplicates) are counted per site per UTC day in `site_stats`;
quarantined spam is counted from feedback. Attempts with an unknown key can't be attributed to
a site and aren't counted.

The admin UI renders all feedback as text (never HTML) and only links `http(s)` URLs.

## Profiles

Users have a first and last name and an optional avatar. Only superadmins can edit names and
emails (`PATCH /users/{id}`). Users manage their own avatar and password:

* `PUT /auth/me/avatar`: raw image body with `Content-Type` image/png, image/jpeg or image/webp
  (content-sniffed; SVG rejected), max `AVATAR_MAX_BYTES` (64 KB). `DELETE /auth/me/avatar` removes it.
* `GET /avatars/{user_id}`: serves the image. Unauthenticated so a plain `<img>` works; ids are
  random UUIDs and nothing else is exposed. API responses carry `avatar_url` (`/avatars/{id}?v=...`),
  and the `v` changes on upload so browsers cache it forever.
* `POST /auth/me/password`: requires the current password and signs out all other sessions.

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
  Rate limits, quotas, honeypot and quarantine are what contain that. For stronger protection add a
  CAPTCHA (Turnstile/hCaptcha) check in `submit_feedback`.

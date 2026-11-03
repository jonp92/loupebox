# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com),
and versions follow [Semantic Versioning](https://semver.org). While the project is alpha (`0.x`), anything may
change between releases; breaking changes are called out below.

## [0.1.0-alpha.1] - Unreleased

First public alpha.

### Added
- **Collect feedback:** sites with public keys and per-site origin allow-lists, a JSON ingest API, and an
  embeddable widget (`/widget/v1/loupebox.js`, Apache-2.0).
- **Abuse controls:** rate limiting, daily quota, honeypot, dedupe, spam quarantine and an optional
  proof-of-work challenge.
- **Triage:** statuses, assignees, tags, internal notes, filters, bulk actions and CSV export.
- **Reply by email** to the person who sent feedback.
- **Notifications:** per-site channels over Brevo, plain SMTP or signed webhooks, delivered by a background
  worker with retries and an hourly cap.
- **Accounts:** per-site roles (viewer, editor, admin), superadmins, password reset by email, TOTP two-factor
  authentication and an audit log.
- **Admin UI:** responsive React app that installs as a PWA, with toasts for action feedback.
- **Deploy:** `./scripts/setup.sh` generates `.env`, Docker Compose for the full stack, a Caddy example, and
  multi-arch images on GHCR (`loupebox-api`, `loupebox-web`).

### Known limitations
- Run a single API replica: rate limiting is in-process until it moves to Redis.
- No inbound email: replies are one-way.
- Not load tested; capacity numbers are estimates.
- The database role and name stay `ganymede` (the project's former name) so existing volumes keep working.

[0.1.0-alpha.1]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.1

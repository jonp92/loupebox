# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com),
and versions follow [Semantic Versioning](https://semver.org). While the project is alpha (`0.x`), anything may
change between releases; breaking changes are called out below.

## [Unreleased]

### Added
- Documentation site at loupebox.dev, built with Zensical from `docs/` and published with GitHub Pages. It has
  install, using, alerts, security and reference pages with screenshots.
- The docs site has a favicon and runs the Loupebox widget, so visitors can send feedback from any page.

### Changed
- The README is now short and points to the docs site. The old one is kept as `README.old`.
- The setup guides moved under `docs/` folders. The internal notifications plan was removed.
- The widget box in site Settings links to the widget docs on the site.

## [0.1.0-alpha.6] - 2026-11-04

### Fixed
- On phones, a member's email on the Members tab was squeezed against the role selector. The role and Remove
  controls now wrap onto their own row.

### Fixed
- On phones, the assignee picker closed as soon as it opened (the on-screen keyboard counted as a resize), and the
  assignee on a feedback card needed a double-click. A tap now opens it.

## [0.1.0-alpha.5] - 2026-11-03

### Fixed
- Signing in while the page was still restoring the previous session could let the stale restore replace the new
  session's token, signing you in as the wrong user or straight back out.

### Changed
- Admin UI redesign around the Loupebox cyan: new dark and light palettes with higher-contrast muted text and
  visible form-control borders. The top bar is always navy, and glows are limited to focus, primary buttons and
  the active tab in dark mode.
- The top bar and sign-in page show the full Loupebox wordmark, with a cyan glow behind the sign-in card.
- `scripts/generate_logos.py` also generates cropped, transparent wordmarks for the app.
- The embeddable widget and the notification emails use the same cyan palette (light and dark), replacing the
  old purple. Widgets that set their own `--gm-*` variables are unaffected.

## [0.1.0-alpha.4] - 2026-11-03

### Changed
- New neon Loupebox logo: the app icon, favicon, PWA icons (including a maskable variant), email logo and the
  README header. The in-app logo follows the light or dark theme. Installed apps pick up the new icons on their
  next update.
- The PWA splash and theme colours now match the icon.

### Added
- Brand artwork in `web/public/brand/` (icon and wordmark, light and dark, text converted to paths so they render
  without fonts), its editable sources in `web/brand/`, and `scripts/outline_brand.py`.
- `scripts/generate_logos.py` now generates every app icon from the one brand icon.

## [0.1.0-alpha.3] - 2026-11-03

### Fixed
- The web image's multi-arch release build no longer stalls: the Node build stage runs on the builder's native
  platform instead of under emulation.
- Version 0.1.0-alpha.2 was tagged but never published (its release build hung), so alpha.3 is the first release
  that includes everything listed under 0.1.0-alpha.2: the release downloads and install command, the footer
  source link, the `.env` fix and the alpha status banner with the backup and upgrade guide.

## [0.1.0-alpha.2] - 2026-11-03 (never published)

### Added
- Each release publishes `docker-compose.yml`, `setup.sh` and `env.example` as downloads, and the README has a
  copy-paste install that needs no clone.
- The admin UI footer shows the version and links to the source.
- Alpha status banner and a backup and upgrade guide in the README.

### Fixed
- The `.env` generated from `.env.example` pinned `ADMIN_ORIGINS` to the dev server, so the API refused the Docker
  UI (HTTP 403 on the CORS preflight) and sign-in failed on a fresh install.
- `web/package.json` now declares its license (`AGPL-3.0-only`).

### Changed
- `setup.sh` runs from the current folder, so it works from a checkout or a release download.

## [0.1.0-alpha.1] - 2026-11-03

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

[0.1.0-alpha.6]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.6
[0.1.0-alpha.5]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.5
[0.1.0-alpha.4]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.4
[0.1.0-alpha.3]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.3
[0.1.0-alpha.2]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.2
[0.1.0-alpha.1]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.1

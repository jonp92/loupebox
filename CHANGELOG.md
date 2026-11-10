# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com),
and versions follow [Semantic Versioning](https://semver.org). While the project is alpha (`0.x`), anything may
change between releases; breaking changes are called out below.

## [Unreleased]

### Changed
- Feedback detail: the data a visitor's page sent along (metadata) is a labelled list instead of a block of JSON:
  yes/no values show a mark and a word, `http(s)` values are links, empty values say so, and the widget version
  sits last. The type badge is not repeated in the list.
- Dashboard: the big number is now what arrived in the last 7, 30 or 90 days (your choice is remembered in the
  browser) with the change against the period before and a per-day sparkline, also per site. "Unread, last 24h"
  and "Sites with unread" are replaced by "Received today" and "Oldest unread", and spam quarantined in the period
  is shown under the band. Every query is an index range scan, none reads a site's whole history.
  **API (breaking):** `GET /dashboard` takes `window=7|30|90`; `received_total` and `new_24h` are replaced by
  `days`, `received`, `received_previous`, `received_today`, `spam`, `oldest_unread_at` and `series`
  (each site in `sites` also has a `series`).
- Feedback detail: customer replies, replies sent by email and internal notes now share one conversation
  timeline. A selector on the form chooses between "Reply to customer (email)" and "Internal note".
- Admin UI: feedback lists are ruled rows instead of cards, with a straight amber bar on unread items. Hovering a
  row (here and on the dashboard) fills the whole row with square corners, so the bar is no longer cut off.
- Audit log: the type and action filters now list what is actually in the log, so exports, personal data,
  retention and image storage events can be filtered, and new audited actions need no UI change.

### Added
- Unread count: the Inbox entry in the sidebar shows how many items are unread across your sites (99+ when large),
  the browser tab title shows it too (`(3) Loupebox Feedback`), and an installed app gets an icon badge where the
  browser supports it. It updates live, including while the tab is in the background.
- System settings: "Metadata keys per submission" (default 20, 13 to 100) sets how many extra keys a visitor's
  submission may carry. `GET /feedback/config` now reports it as `metadata_max_keys`.
- Live updates: the admin UI refreshes itself when feedback arrives, is triaged or answered (including by email),
  and when notes or replies are added, with no reload and no polling. `GET /v1/api/events` is a server-sent
  event stream of `{kind, site_id, feedback_id}` (ids only, the page refetches), limited to the caller's sites
  and closed when the access token expires. On Postgres every API process listens for NOTIFY, so events raised by
  the worker reach all replicas; no new service is needed. If the proxy buffers responses (nginx:
  `proxy_buffering off`) or the database sits behind a transaction-pooling pgbouncer (LISTEN does not work
  there) the page just falls back to updating on reload.
- System status shows an **Inbound email** row for each mailbox the worker reads: when it was last read and last
  stored, how many emails matched, did not match or bounced in the last 24 hours, or the error it is failing with.
  It warns when the mailbox has not been read for a while (worker stopped) or unmatched mail keeps arriving.
- Answers by email: a person's answer to a reply is read from an IMAP mailbox and shown in the conversation as a
  **Customer** entry, and the item goes back to unread. Replies carry a `replies+code@your-domain` Reply-To, only
  the person who wrote the feedback can answer, quoted text is cut, automatic replies are ignored and a bounce
  marks your reply as failed. Off until `INBOUND_ADDRESS` and `IMAP_HOST` are set (also on the System page).
  Webhook channels can subscribe to `feedback.customer_replied`. Sources are pluggable (`app/inbound/sources/`).
- System settings: minimum password length, and an option to require two-factor authentication for everyone.
  `python -m scripts.reset_totp --stop-requiring` removes the requirement if no one can sign in.
- Webhook channels can include the reply text in `feedback.replied` events (off by default).
- Notification channels can be limited to the items they care about: issue type, rating range, whether an
  email was left, and part of the page address. Migration `0021`.

## [0.1.0-alpha.12] - 2026-11-07

### Added
- An **Inbox** across all your sites (sidebar, for anyone on more than one site, and for superadmins). One list,
  newest first, with each item's site, the usual filters plus a Site filter, tabs for All, Unread, My work and
  Unassigned, and bulk status change and "assign to me" for the items you can edit. The item page's back link returns
  to the filtered inbox. The Dashboard links into it. **API:** `GET /inbox`, `GET /inbox/counts`, `POST /inbox/bulk`.

### Changed
- The Users list draws only what stands out: the Superadmin badge and a Disabled account. A plain user and an active
  account are shown as quiet text (and not at all on phones, where they are still read out by screen readers). "2FA off"
  is a muted ring instead of a red dot, since 2FA is optional and red is kept for real problems.

## [0.1.0-alpha.11] - 2026-11-07

### Changed
- The admin app has a new look: brass and sage palette from shared design tokens, Hanken Grotesk and IBM Plex Mono
  (self-hosted, no CDN), a sidebar with a mobile drawer, and a redrawn logo in brass (same loupe, lettering in the UI
  font). Favicons, app icons and the email logo were regenerated to match, from one script (`scripts/brand_art.py`).

### Added
- Images can be stored in an S3 bucket: Amazon S3 or any S3-compatible service (Cloudflare R2, Backblaze B2,
  DigitalOcean Spaces, Wasabi, MinIO, Ceph and others). It is set up in the admin app under **System → Image
  storage** (endpoint address, region, bucket, access key, secret key, path-style, folder; for local storage, the images folder; the secret is write-only
  and stored encrypted), with a **Test connection** button that writes, reads back and deletes a probe file and says
  what is wrong. Each image remembers where its file is (migration `0020`), so switching the storage never strands
  existing images, and a **Move images** button copies them over a few at a time. Services without a bulk delete
  (Scality CloudServer and others) are handled. Sites show a warning, and the widget offers no image upload, while
  the chosen storage is not set up. New dependency: `boto3`. **API:** `GET /system/storage`,
  `POST /system/test-storage`, `POST /system/storage/move`, `attachments_ready` on sites.
- "Capture this page" in the widget, on desktop browsers that can share a screen (`capture: false` or
  `data-capture="false"` turns it off; capability `capture`). The visitor picks what to share, the widget hides
  itself for the moment the picture is taken, and a full-screen editor opens: solid black boxes hide anything private
  (burned into the picture in the browser; the original is never sent), a highlighter points out the problem, with
  undo and clear. It can be used with the keyboard as well as a pointer. The result is attached like any image.
- The personal-data export is now a zip (`person-export.zip`): `data.json` plus the pictures the person sent, in an
  `images` folder. Pictures past `PERSON_EXPORT_MAX_BYTES` (500 MB) are listed in `data.json` with a note instead.
  **Changed:** the export used to be a JSON file.
- Images with feedback, opt-in per site (Settings → "Accept images with feedback", migration `0019`). The widget
  gets an Add image button and takes pasted or dropped images; large ones are scaled down in the browser. The
  server accepts PNG, JPEG and WebP only, decodes and re-encodes every image (EXIF and anything hidden in the
  file is dropped, large pictures are scaled to 2048 px), and refuses the whole submission if one image is bad.
  Limits: 3 images, 5 MB each (`ATTACHMENT_MAX_COUNT`, `ATTACHMENT_MAX_BYTES`, `ATTACHMENT_MAX_EDGE`).
  Files go through a storage backend (`STORAGE_BACKEND=local`, folder `ATTACHMENTS_DIR`; a volume in the Docker
  setup); more backends can be added. Images are served only to signed-in members of the site, shown as a
  thumbnail grid with a full-size viewer on the item page, and counted on the list. Admins can delete one image.
  They are deleted with their feedback (single, bulk, retention, erase, site delete), and a daily sweep removes
  stray files. **API:** `GET /feedback/config`, `POST /feedback/with-images` (multipart; the JSON endpoint is
  unchanged), `GET|DELETE /sites/{id}/feedback/{id}/attachments[/{id}]`, `attachments_enabled` on sites,
  `attachment_count` on feedback. `backup.sh` and `restore.sh` now include the image files.
- The widget starts from a script tag alone: `<script type="module" src=".../loupebox.js" data-key="pk_...">`,
  with `data-` attributes for the common options and no inline script. Capabilities `images` and `auto-init`.
- Per-site retention: a site's admins can delete feedback after a number of days and/or remove submitters'
  email addresses after a number of days (migration `0018`). The worker applies it hourly, in batches, and
  clears the matching sent and failed alert copies too. Off by default. **API:** `retention_delete_days` and
  `retention_strip_email_days` on `PATCH /sites/{id}`.
- Site admins can export (JSON, with replies and notes) or erase the personal data held for one email
  address, from the site's Settings page. **API:** `POST /sites/{id}/privacy/lookup|export|erase`. The address
  travels in the body, and the audit log records counts only.
- The System page's Status tab lists the latest failed notifications of the last 24 hours (site, channel,
  attempts and the provider's error), only when there are some. Errors are shortened and URLs are reduced to
  their host, so webhook tokens stay out of view.
- The System page's Email tab has a "Send test to me" button for each email provider, so you can check a
  provider works before relying on it. **API:** `POST /system/test-email` (superadmin only).
- The System page's Status tab has a "Finish setting up" list: email provider, admin UI address, worker
  running, a site, a notification channel. It disappears once everything is done.
- The System page is split into tabs (Status, Email & notifications, Public form, Accounts & limits), each at
  its own address under `/system/`.
- The System page's Status tab shows instance health: the database, whether the worker is running (it now
  records a heartbeat, migration `0015`), the outbox backlog and, when `REDIS_URL` is set, Redis. **API:**
  `GET /system/health` (superadmin only).
- You can run more than one API container. Set `REDIS_URL` and the rate limits are shared through Redis
  instead of each container counting on its own. The compose file has an optional `redis` service
  (`--profile redis`). Without `REDIS_URL` nothing changes.
- Settings saved on the System page reach other API containers within 30 seconds.

### Changed
- Searching feedback on Postgres uses trigram indexes (migration `0017`, extension `pg_trgm`). On a benchmark
  database of 1.1 million items, a search for a rare word on the largest site (237,000 items) dropped from about
  150 ms to under 1 ms per query. Under a rising load of searches the 95th percentile stayed under 190 ms up to
  the highest rate tried (a ramp to 16 per second); without the indexes it was 3.8 s at a ramp to 12 and requests
  began to fail at 14. Building the indexes took about 35 seconds there
  and added 225 MB to a 548 MB table, and new feedback waits while they build. If the database does not allow
  the extension, the migration prints a warning and continues: search works as before, only slower on big sites.
- Turning on two-factor authentication asks for your password as well as the first code, as turning it off
  already did. **API:** `POST /auth/me/totp/enable` now requires `password`.

### Fixed
- The admin app's Content-Security-Policy refused the blob: addresses the feedback gallery shows its images from,
  so images did not appear on the item page. `img-src` now allows `blob:`. Only the page's own script can create
  one, and scripts are still limited to the app itself. Run `docker compose pull` and restart the `web` container.
- A burst of requests could leave the API unresponsive for many minutes: requests waiting for a database
  connection filled every worker thread, and the requests holding the connections could not finish. The API
  now handles only as many requests at once as its database pool can serve, and the rest wait briefly or get
  a `503` with `Retry-After`. Also, the list of allowed origins no longer reloads on the server's event loop,
  where a full pool could freeze the whole server. New settings: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
  `DB_POOL_TIMEOUT`, `MAX_CONCURRENT_REQUESTS`, `REQUEST_QUEUE_SECONDS`.
- An allowed origin saved with its default port (`https://example.com:443`) never matched, because browsers
  leave the default port out of the Origin header. The port is now dropped when saving, and migration `0014`
  fixes origins already stored.
- The daily feedback limit can no longer be overshot by submissions arriving at the same moment.
- The light theme's selected-row background is a touch lighter so the accent text on it meets 4.5:1 contrast.
- Phones no longer pop up the on-screen keyboard when a sheet or sign-in page opens (autofocus now applies to devices with a mouse or trackpad only), and spacing under key, hint and save controls is tighter. The "Assigned to me" tab is now "My work".

## [0.1.0-alpha.10] - 2026-11-06

### Changed
- The admin UI and widget build on React 19, Vite 8 and TypeScript 7. Nothing changes for users or embedders.

### Fixed
- The feedback item menu (⋯, right-click or long-press) lists its actions one per line instead of running them
  together, and its items are at least 44px tall on touch screens.

## [0.1.0-alpha.9] - 2026-11-06

### Added
- Compact view for the feedback list on wide screens: two short lines per item with the message cut to one line,
  aligned columns and 50 items per page. Switch between Comfortable and Compact above the list; the choice is
  kept in this browser.

### Changed
- **Breaking (API):** `GET /users` returns one page as `{items, total}` instead of a list, and takes `q` (name or
  email contains), `limit` (default 50, max 200) and `offset`.
- The Users page is a table with search and paging (50 per page). Edit and a ⋯ menu replace the four buttons per
  row, phones get one compact card per user, and **New user** opens the form above the list.
- Feedback cards on phones are tighter: two-line message preview and less padding.

### Fixed
- The whole feedback card now opens the item, not just the message text. The checkbox, ⋯ menu, assignee and
  notes count still do their own thing, and Cmd/Ctrl-click or middle-click opens the item in a new tab.

### Security
- Docker installs made from the quickstart ran in development mode: `env.example` set `ENVIRONMENT=development`
  for running the API on the host, and docker compose read it too. That published the API docs at
  `/v1/api/docs` and skipped the production checks. The line is gone from the template. **If you installed with
  the quickstart, delete `ENVIRONMENT=development` from your `.env`** and run `docker compose up -d`. Check
  first that `JWT_SECRET` and the three `*_ENCRYPTION_KEY` settings are filled in (`setup.sh` does this),
  because production refuses to start without them.

## [0.1.0-alpha.8] - 2026-11-05

### Upgrading
- **Production now refuses to start without `TOTP_ENCRYPTION_KEY`, `WEBHOOK_ENCRYPTION_KEY` and
  `SETTINGS_ENCRYPTION_KEY`.** Installs made with an older `setup.sh` must add `SETTINGS_ENCRYPTION_KEY` to `.env`
  (any random string, for example `openssl rand -base64 48`). If `TOTP_ENCRYPTION_KEY` or `WEBHOOK_ENCRYPTION_KEY`
  was empty, set it to your current `JWT_SECRET`, so existing two-factor and webhook secrets stay readable.
- Migration `0013` adds the `app_settings` table. The `migrate` service applies it on `docker compose up -d`.

### Added
- System settings page for superadmins (`/system`, `GET`/`PATCH /settings`): change email, notification,
  rate-limit, sign-in and retention settings without a restart. Saved values win over `.env` and every change is
  audited. The SMTP password and Brevo API key are write-only and stored encrypted with the new
  `SETTINGS_ENCRYPTION_KEY` (`setup.sh` generates it; set it in existing `.env` files). Migration `0013`.
- The dashboard shows the total non-spam feedback received across your sites, and an "Unread by site" list that
  opens each site with the unread filter on. `GET /dashboard` returns the total as `received_total`.

### Changed
- "Latest unread" on the dashboard opens the feedback item itself, not the site's list.
- Users who belong to a single site skip the Sites list and land on that site's feedback.
- **Breaking:** with `ENVIRONMENT=production`, the API and worker refuse to start unless `TOTP_ENCRYPTION_KEY`,
  `WEBHOOK_ENCRYPTION_KEY` and `SETTINGS_ENCRYPTION_KEY` are set; they no longer fall back to `JWT_SECRET`. Installs
  made with `setup.sh` before this release need `SETTINGS_ENCRYPTION_KEY` added to `.env`. If you ran without the
  other two, set them to your current `JWT_SECRET` so existing two-factor and webhook secrets stay readable.

### Fixed
- Pressing Enter on the sign-in form right after the page opened did nothing on a slow server. The form now
  appears once the session check is done, and Enter always signs in.
- The favicon is now a transparent glyph (SVG, `.ico` and 16/32px PNGs, all declared in `index.html`), so Safari
  no longer shows a light border around it in the tab bar. The docs site uses the same favicon.
- The app header and login wordmark is an SVG with a 176px-high PNG fallback.

### Security
- The add-member picker no longer lets a site admin list every user on the instance. It suggests people
  who share one of the admin's sites; anyone else is found only by their full email address. Superadmins still
  search everyone.

## [0.1.0-alpha.7] - 2026-11-04

### Added
- Documentation site at loupebox.dev, built with Zensical from `docs/` and published with GitHub Pages. It has
  install, using, alerts, security and reference pages with screenshots.
- The docs site has a favicon and runs the Loupebox widget, so visitors can send feedback from any page.
- `backup.sh` and `restore.sh` (also release downloads): one dated file with the database and `.env`, keeping
  the newest 14. `DB_DATA_DIR` in `.env` keeps the database in a folder instead of a Docker volume.

### Changed
- The README is now short and points to the docs site. The old one is kept as `README.old`.
- The setup guides moved under `docs/` folders. The internal notifications plan was removed.
- The widget box in site Settings links to the widget docs on the site.
- Python dependencies are pinned. Edit `requirements.in` / `requirements-dev.in` and run `pip-compile` to
  regenerate `requirements.txt` / `requirements-dev.txt`; images and CI install the exact versions.
- Dependabot opens weekly update PRs for pip, npm, GitHub Actions and the Docker base images.
- The web image serves from nginx 1.31 and builds with Node 26.
- Python code is formatted with `ruff format`, and CI checks formatting, line length, likely bugs and complexity.

### Security
- Sign-in stops an account after 10 wrong passwords in 15 minutes, counted per email across all IPs
  (`LOGIN_FAILURE_LIMIT`, `LOGIN_FAILURE_WINDOW_SECONDS`). Only failures count, and a successful sign-in or
  password reset clears them. Unknown emails are limited the same way, so the limit reveals nothing.
- Admin UI build updated to vite 6.4 and react-router 7.18, which fixes 11 dependency advisories.

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

[0.1.0-alpha.10]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.10
[0.1.0-alpha.9]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.9
[0.1.0-alpha.8]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.8
[0.1.0-alpha.7]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.7
[0.1.0-alpha.6]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.6
[0.1.0-alpha.5]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.5
[0.1.0-alpha.4]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.4
[0.1.0-alpha.3]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.3
[0.1.0-alpha.2]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.2
[0.1.0-alpha.1]: https://github.com/jonp92/loupebox/releases/tag/v0.1.0-alpha.1

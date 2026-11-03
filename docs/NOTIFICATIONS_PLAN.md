# Notification plugins (Brevo first): plan

Status: **implemented** (phases 1-4). Decisions below are settled. Setup: [BREVO_SETUP.md](BREVO_SETUP.md).

## Goal

When feedback arrives, notify the right people through pluggable channels. The first provider is
**Brevo** (email). The design must make a second provider (Slack, a webhook, ...) a single new file.

## Decisions

| Question | Decision |
|---|---|
| Recipients | Site members at or above a chosen role, plus optional extra addresses |
| Timing | Instant, with a per-channel hourly cap; overflow rolls into one summary email |
| Brevo credentials | Server env vars, operator-owned. No secrets in the database or the UI |
| Delivery | Transactional outbox table in Postgres, drained by a **separate worker service** |
| Redis | **Not now.** Postgres is the queue. Revisit only when running more than one API process |
| Worker | Own compose service, same image, `python -m app.worker` |
| Hourly cap | 5 emails per channel per hour (configurable). Summary goes out about 15 minutes after the cap is hit |
| Reply-To | The submitter's address, when they gave a valid one |

## Why no Redis yet

The outbox table is the queue, and workers claim rows with `FOR UPDATE SKIP LOCKED`, so Redis would
add a service to run and back up without solving a current problem. It becomes worthwhile if the API
is scaled beyond one process: the in-process rate limiter (`app/core/rate_limit.py`) would then need a
shared store. Keep the dispatcher and rate limiter behind small interfaces so that swap stays
contained.

## Flow

```
submit feedback ──► INSERT feedback + INSERT outbox row (same DB transaction)
                              │
worker (loop) ◄───────────────┘  claims due rows, resolves recipients,
   │                             applies hourly cap, calls provider.send()
   ▼
provider plugin (Brevo) ──► sent / retry with backoff / failed (visible in UI)
```

Writing the outbox row in the same transaction as the feedback means a crash can neither lose a
notification nor send one for feedback that was never stored.

## Plugin contract (`app/notifications/`)

* `events.py`: typed events (Pydantic). Version 1 has only `feedback.created`.
* `base.py`: `NotificationProvider` abstract class:
  * `key`, `label`
  * `ConfigModel`: Pydantic model for the provider's per-channel settings
  * a check for required server settings (e.g. env vars present)
  * `send(message, config)` returning `sent` (with provider message id), `retry` or `failed`
* `registry.py`: `@register_provider` decorator; providers in `providers/*.py` load at startup.
  Entry-point loading for external packages can come later.
* The admin UI renders each provider's form from `ConfigModel.model_json_schema()`, so a new provider
  needs no UI work.
* A webhook-style provider would additionally need SSRF protection (block private and link-local
  addresses). Brevo does not, since its URL is fixed.

## Brevo provider (`providers/brevo.py`)

* `POST https://api.brevo.com/v3/smtp/email`, header `api-key: <BREVO_API_KEY>`, JSON body:
  `sender {email,name}`, `to [{email,name}]`, `subject`, `htmlContent`, `textContent`,
  `replyTo {email,name}`, `tags`. Use `httpx` with a 10 s timeout.
* Success is `201` with `{"messageId": "..."}`; store the id on the outbox row.
* Error mapping by status class: `400`, `401`, `403` are permanent failures; `429`, `5xx`, timeouts
  and connection errors are retried. Brevo's reference page documents only the `400` error body
  (`{"code","message"}`), so confirm the other codes against a real account while implementing.
* One API call per recipient so recipients' addresses are never exposed to each other.
* Server settings: `BREVO_API_KEY`, `NOTIFY_SENDER_EMAIL`, `NOTIFY_SENDER_NAME`, `PUBLIC_URL`.
  Never log the key or full message bodies.

References: <https://developers.brevo.com/reference/sendtransacemail>

## Data model (one migration, `0005`)

`notification_channels`
: `id`, `site_id` (FK, cascade), `provider`, `name`, `enabled`, `config` (JSON, no secrets),
  `events` (JSON list), `min_role` (`viewer`/`editor`/`admin`), `extra_recipients` (JSON list),
  `created_at`, `updated_at`

`notification_outbox`
: `id`, `channel_id` (FK, set null on delete so the log survives), `site_id`, `event_type`,
  `payload` (JSON), `status` (`pending`, `sending`, `sent`, `failed`, `held`), `attempts`,
  `next_attempt_at`, `last_error` (truncated), `provider_message_id`, `created_at`, `sent_at`.
  Index on `(status, next_attempt_at)`.

## Delivery rules

* **Triggers:** accepted feedback only. Quarantined spam, honeypot drops and duplicates never email.
* **Recipients:** resolved at send time, not at enqueue: active members with role at or above
  `min_role`, plus `extra_recipients`, deduplicated and capped at 20 per channel. Membership changes
  apply automatically.
* **Hourly cap and summary:** past 5 sends per channel per hour, new rows become `held`. About 15
  minutes after the cap is hit the worker sends one summary ("N more feedback items") with the first
  few excerpts, then marks them `sent`. This protects Brevo's free plan (300 emails a day), since
  anyone can trigger notifications through the public form.
* **Retries:** wait 30 s, 2 min, 10 min, 1 h, 6 h, then `failed`. Rows stuck in `sending` for over
  5 minutes are reclaimed.
* **Retention:** delete `sent` and `failed` rows after 30 days.
* **Guarantee:** at-least-once. A crash right after Brevo accepts an email can, rarely, send a
  duplicate. Accepted.
* **Email content:** plain text plus simple HTML. Escape all user text, cap the excerpt at 500
  characters, link to the site in the admin UI (`PUBLIC_URL`), Reply-To is the submitter when valid.
  Subject: `New feedback on <site name>`.

## Worker

`python -m app.worker` as a new compose service (same image, `restart: unless-stopped`, depends on
`db` and `migrate`). Polls every few seconds. Uses `SKIP LOCKED` on Postgres and a simple path on
SQLite so the test suite still runs there.

## Admin API (site admins only, under `/v1/api`)

* `GET /notifications/providers`: key, label, whether configured on the server, config JSON schema
* `GET|POST /sites/{id}/notifications`, `PATCH|DELETE /sites/{id}/notifications/{cid}`
* `POST /sites/{id}/notifications/{cid}/test`: sends only to the requesting admin; rate-limited
* `GET /sites/{id}/notifications/deliveries`: last 50 attempts, error text, no secrets
* Validate extra addresses; refuse to enable a channel whose provider isn't configured on the server.

## Admin UI

A **Notifications** tab per site (admin role): channel list with status badges; add/edit form built
from the provider schema plus shared fields (name, events, minimum role, extra recipients, enabled);
"Send test to me"; delivery log table; a warning when the provider isn't configured on the server.

## Phases

| # | Deliverable |
|---|---|
| 1 | Models, migration, event, provider interface, registry, enqueue on submit, worker with retry and backoff |
| 2 | Brevo provider, templates, recipient resolution, hourly cap and summary |
| 3 | Admin API and the Notifications tab |
| 4 | Compose worker service, docs, Brevo setup guide |

## Testing

* Provider contract tests with a fake provider; Brevo against `httpx.MockTransport` (headers, payload,
  error-class mapping).
* Worker: enqueue is atomic with the feedback insert, backoff schedule, cap then held then summary,
  role-based recipients, disabled and deleted channels, stuck-row reclaim.
* API: role matrix, validation, test-send limits, secrets never returned.
* UI: build plus the same headless-browser checks used for the other tabs.
* One live send with the real Brevo key, run manually.

## Prerequisites on the Brevo side

* An account and API key (v3).
* A verified sender, e.g. `feedback@example.com`.
* Domain authentication (DKIM) for `example.com`. Without it Brevo replaces the sending domain
  with its own `brevosend.com`, which hurts deliverability.
* Free plan allows 300 sends per day, including transactional API sends.

## Out of scope for version 1

Per-user opt-out, custom email templates, and further events (site daily limit reached, spam spikes).
The design supports them. Password-reset and invite emails are the natural next consumer: they would
use the same provider but a system-mail path that is not tied to a site channel.

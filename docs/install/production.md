# Production checklist

Check these before you use Loupebox in production.

* `ENVIRONMENT=production`.
* `JWT_SECRET` is at least 32 characters. `setup.sh` generates a good one.
* `TOTP_ENCRYPTION_KEY`, `WEBHOOK_ENCRYPTION_KEY` and `SETTINGS_ENCRYPTION_KEY` are set. With
  `ENVIRONMENT=production` the API and worker refuse to start without them. `setup.sh` generates them.
* `COOKIE_SECURE=true`, because you serve the admin app over HTTPS.
* If the admin app and the API are on different sites (not just different subdomains), also set
  `COOKIE_SAMESITE=none`. Using one domain for both avoids this.
* Behind a reverse proxy, set `TRUST_PROXY=true`, and make sure the proxy replaces the
  `X-Forwarded-For` header and nobody can reach the API port directly.
* Run **one** API container, or set `REDIS_URL` first. See
  [More than one API container](#more-than-one-api-container).
* Run the **worker**. Without it no alerts are sent.
* Set up [email](../notifications/index.md) so people get alerts and can reset passwords.
* Back up the database on a schedule, and test a restore once. See [Backups](backups-upgrades.md).
* Turn on [two-factor sign-in](../security/two-factor.md) for administrators.

## A public key cannot stop a determined attacker

The site key is in your web page, and a script can fake the browser's origin header. Loupebox limits the
damage with rate limits, daily quotas, a hidden honeypot field and a spam quarantine. If you still get
junk, turn on a challenge for the site. See [Spam and bots](../collect/spam-and-bots.md).

## More than one API container

Rate limits are kept in the API's memory by default. With two API containers each one counts separately, so
visitors get double the limit. To run more than one, keep the counts in Redis:

1. Start the Redis service that comes with the compose file: `docker compose --profile redis up -d`.
2. Add `REDIS_URL=redis://redis:6379/0` to `.env` and restart the API.

Redis only holds rate-limit counters, so it needs no volume or backup. The keys are hashed, so it never
stores email or IP addresses. If Redis goes down, each API container keeps counting in its own memory and
tries Redis again a few seconds later.

Settings saved on the System page reach the other API containers within 30 seconds. One worker is enough,
but more are safe on Postgres.

## Search on a large database

Search looks for the text anywhere in the message, name and email address. On Postgres, Loupebox speeds this up
with trigram indexes from the `pg_trgm` extension, created by a database migration when you upgrade. You do
not need to do anything on the bundled Postgres, or on Postgres 13 or later, where the database owner may
create this extension.

* **Small inboxes do not need it.** A site with a few thousand items searches in about 10 ms either way. The
  difference shows on sites with hundreds of thousands of items.
* **The migration blocks new feedback while it builds the indexes.** That is a few seconds per 100,000 items,
  and about 35 seconds for 1 million.
* **If your database does not allow the extension**, the upgrade still finishes and prints a warning that
  `pg_trgm` is not available. Search keeps working, slower on big sites. To add the indexes later, run
  `CREATE EXTENSION pg_trgm;` as a superuser in the Loupebox database, then run
  `alembic downgrade 0016 && alembic upgrade head` in the API container.
* **SQLite** has no such indexes. It is meant for trying Loupebox out, not for large inboxes.

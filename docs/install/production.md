# Production checklist

Check these before you use Loupebox for real feedback.

* `ENVIRONMENT=production`.
* `JWT_SECRET` is at least 32 characters. `setup.sh` generates a good one.
* `COOKIE_SECURE=true`, because you serve the admin app over HTTPS.
* If the admin app and the API are on different sites (not just different subdomains), also set
  `COOKIE_SAMESITE=none`. Using one domain for both avoids this.
* Behind a reverse proxy, set `TRUST_PROXY=true`, and make sure the proxy replaces the
  `X-Forwarded-For` header and nobody can reach the API port directly.
* Run **one** API container. Rate limits are kept in the API's memory, so with two copies each visitor
  gets double the limit. See [Known limits](../reference/limitations.md).
* Run the **worker**. Without it no alerts are sent.
* Set up [email](../notifications/index.md) so people get alerts and can reset passwords.
* Back up the database on a schedule, and test a restore once. See [Backups](backups-upgrades.md).
* Turn on [two-factor sign-in](../security/two-factor.md) for administrators.

## A public key cannot stop a determined attacker

The site key is in your web page, and a script can fake the browser's origin header. Loupebox limits the
damage with rate limits, daily quotas, a hidden honeypot field and a spam quarantine. If you still get
junk, turn on a challenge for the site. See [Spam and bots](../collect/spam-and-bots.md).

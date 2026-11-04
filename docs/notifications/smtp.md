# SMTP setup

Besides Brevo, Loupebox can send email through any ordinary SMTP server: your own relay, a mail host's
SMTP service, or a local test server. Pick it as the **SMTP (email)** provider when adding a channel. It
works exactly like the Brevo provider: same recipients, same hourly cap and summary, same templates.

Settings are server-side only (they are never stored in the database or shown in the UI). Put them in the
`.env` used by docker compose:

```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls          # starttls (587), ssl (465) or none
SMTP_USERNAME=feedback@example.com
SMTP_PASSWORD=...
NOTIFY_SENDER_EMAIL=feedback@example.com     # the From address; many servers require it to match the login
NOTIFY_SENDER_NAME=Loupebox
```

| `SMTP_SECURITY` | Meaning |
|-----------------|---------|
| `starttls` (default) | Connect, then upgrade to TLS. If the server does not offer STARTTLS the send **fails**; it never falls back to plaintext. |
| `ssl` | TLS from the first byte (usually port 465). |
| `none` | No encryption. Only for a relay on a trusted network. **Credentials are never sent this way**: with `SMTP_USERNAME` set, `none` counts as not configured. |

Certificates are verified against the system trust store, including the host name. A server with a
self-signed or mismatched certificate fails with "TLS certificate not trusted"; fix the certificate rather
than looking for a switch to turn checking off. `SMTP_TIMEOUT` (seconds, default 15) bounds each step.

## Common hosts

* **Fastmail, Zoho, Mailgun, SES, Postmark...**: use the SMTP host, port 587 and `starttls`, with the
  SMTP credentials they give you (often an app password or API key, not your login password).
* **Gmail / Google Workspace**: `smtp.gmail.com`, 587, `starttls`, with an *app password* (requires 2-step
  verification). Gmail rewrites the From address to the account unless it is a verified alias.
* **A relay on the same Docker network** (Postfix, Mailpit for testing): `SMTP_HOST=<service name>`,
  port 25 or 1025, `SMTP_SECURITY=none`, no username.

## Deliverability

Send from a domain you control and publish SPF and DKIM records for it that include your SMTP host;
without them messages often land in spam. Free-mail From addresses (gmail.com, icloud.com...) sent through
someone else's server are frequently rejected for the same reason.

## Behaviour

* One connection per send, one message per recipient, so addresses stay private from each other.
* `4xx` replies, dropped connections and timeouts are retried (30 s, 2 min, 10 min, 1 h, 6 h). `5xx`
  replies (bad credentials, refused recipient, rejected message) fail immediately. Delivery is at least
  once: a retry after a partial failure can send a duplicate.
* The EHLO name is the sender's domain, not the container's hostname, which receiving servers distrust.
* Password-reset and other account mail use whichever email provider is configured. If both Brevo and SMTP
  are set up, set `MAIL_PROVIDER=smtp` (or `brevo`) to choose; otherwise Brevo is used first.

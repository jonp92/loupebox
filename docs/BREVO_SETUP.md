# Brevo setup

Ganymede sends notification emails through Brevo's HTTP API (`POST /v3/smtp/email`). It does not use
SMTP, so SMTP credentials will not work.

## 1. Account and sender

1. Create a Brevo account. The free plan allows 300 emails a day.
2. **Senders, domains & dedicated IPs → Senders**: add the address you want mail to come from and
   verify it. Unverified senders are rejected by Brevo.
3. For good deliverability, authenticate the sending domain (**Domains**): add the DKIM record (and
   the Brevo code and DMARC records it lists) in your DNS.

## 2. API key

1. **SMTP & API → API Keys → Generate a new API key.** It starts with `xkeysib-`.
2. Permissions: set **Transactional email** to **All** and leave every other resource on **None**.
   Sending is a `POST`, and Transactional email offers only None, Read and All, so All is the lowest
   level that works.
3. Keys expire after 90 days unused (and have a fixed expiry date). If the app sends nothing for 90 days
   the key stops working; rotate it before the expiry date shown in Brevo.
4. If you restrict **Security → Authorised IPs**, allow the server that runs the worker and API.

## 3. Configure

In the `.env` used by docker compose (see `deploy/production.env.example`):

```
BREVO_API_KEY=xkeysib-...
NOTIFY_SENDER_EMAIL=feedback@example.com     # the verified sender
NOTIFY_SENDER_NAME=Ganymede
PUBLIC_URL=https://feedback.example.com      # for links in emails
```

Restart so the API and worker pick it up: `docker compose up -d`. The **Brevo (email)** provider is
disabled in the UI until the key and sender are both set.

## 4. Check it works

1. In the UI, open a site → **Notifications**, add a Brevo channel, and click **Test**. The test email
   goes only to you.
2. Submit feedback to the site and watch the **deliveries** list: a row moves from pending to sent.
3. `docker compose logs -f worker` shows what the worker is doing.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Provider disabled in the UI | `BREVO_API_KEY` or `NOTIFY_SENDER_EMAIL` missing, or the API was not restarted |
| Rows stay `pending` | The worker is not running, or points at a different database |
| Failed with 401 / 403 | Wrong key, key lacks Transactional email **All**, expired key, or the server IP is not authorised |
| Failed with 400 | Sender not verified in Brevo, or an invalid recipient address |
| `held` rows, then one summary email | Hourly cap (`NOTIFY_HOURLY_CAP`) reached for that channel; this is intended |
| Retries (429, 5xx, timeouts) | Retried at 30s, 2m, 10m, 1h, 6h, then failed |

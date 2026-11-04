# Email alerts

Loupebox can email people when new feedback arrives, or post it to another service as a
[webhook](webhooks.md). You set this up per site.

![A site's notification channels](../images/notifications-dark.png#only-dark)
![A site's notification channels](../images/notifications-light.png#only-light)

## What you need

1. A way to send email. Choose one:
    * [Brevo](brevo.md), which has a free plan and needs an API key.
    * [SMTP](smtp.md), which works with almost any mail server or mail host.
2. The **worker** running. The API only puts alerts in a queue. The worker sends them and tries again if
   sending fails. In Docker it starts with everything else. Without Docker, run `python -m app.worker`.
3. A **sender address** in `.env`: `NOTIFY_SENDER_EMAIL`, and optionally `NOTIFY_SENDER_NAME`.

Until the provider is set up, it shows as disabled in the app.

## Add a channel

A site admin opens the site's **Notifications** tab, adds a channel, picks a provider and lists who should
receive the alerts. Use the test button to send one right away.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `PUBLIC_URL` | none | Your admin app's address. Adds links to alert emails and turns on "Forgot password?". |
| `NOTIFY_HOURLY_CAP` | 5 | Most emails per channel per hour. Extra alerts are rolled into one summary email. |
| `NOTIFY_RETENTION_DAYS` | 30 | Sent and failed alerts are deleted after this many days. |

Password-reset and reply emails do not go through the queue. They are sent straight away, so a live reset
link is never stored. If both Brevo and SMTP are set up, `MAIL_PROVIDER` (`brevo` or `smtp`) picks which one
sends them.

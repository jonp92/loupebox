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

## Only some items

Under **Only notify when**, a channel can be limited to the items it cares about, for example bug reports
rated 1 or 2 going to a webhook while the team inbox still gets everything:

* **Type** of issue, from the widget's badges, or "No issue type".
* **Lowest** and **highest rating**. Items without a rating never match a rating limit.
* Whether the person **left an email address**.
* Part of the **page address**, ignoring capitals.

Leave a field empty to ignore it. Fields you set must all match, but several types are alternatives. The
same limits apply to reply events (`feedback.replied`), judged by the item that was replied to. They work for
every kind of channel, are checked when the item arrives, and don't change anything already sent. **Send
test** ignores them, so you can always check that a channel works. Tags and the assignee can't be used,
because a new item has neither yet.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `PUBLIC_URL` | none | Your admin app's address. Adds links to alert emails and turns on "Forgot password?". |
| `NOTIFY_HOURLY_CAP` | 5 | Most emails per channel per hour. Extra alerts are rolled into one summary email. |
| `NOTIFY_RETENTION_DAYS` | 30 | Sent and failed alerts are deleted after this many days. |

Password-reset and reply emails do not go through the queue. They are sent straight away, so a live reset
link is never stored. If both Brevo and SMTP are set up, `MAIL_PROVIDER` (`brevo` or `smtp`) picks which one
sends them.

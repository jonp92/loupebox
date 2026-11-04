# Reply to people

If the person left an email address, an editor can answer from the item's page.

![Replying to a feedback item](../images/reply-dark.png#only-dark)
![Replying to a feedback item](../images/reply-light.png#only-light)

The reply is emailed with their original message quoted. **Reply-To is set to you**, so when they answer,
it goes to your own inbox. Loupebox does not read incoming mail, so replies from the person do not show up in
the app.

## Before you start

Replies need a working [email service](../notifications/index.md). They use the provider named by
`MAIL_PROVIDER`, which is also the one that sends password resets.

## What to expect

* Replies are sent right away, not queued. The item shows the result. **Sent** means the mail server
  accepted the message, not that the person received it. **Failed** shows the server's reason.
* After a temporary failure there is a **Try again** button. After a refused address there is not.
* You can send up to 5 replies per item (`REPLY_MAX_PER_ITEM`) and 30 per site per hour
  (`REPLY_SITE_HOURLY_LIMIT`).
* You cannot reply to spam, or to items without an email address.
* Viewers can read the conversation. Editors send.
* The person's address is shown partly hidden in the app.
* The [audit log](../security/audit-log.md) records that a reply happened and how it went, but not its text
  or the address.
* Webhook channels can subscribe to `feedback.replied`. It carries ids and the reply length, not the text.

## What Loupebox is not

Loupebox is an inbox for feedback on small tools. It has no ticket statuses, queues or response-time
targets, and none are planned. If you want a help desk, use a [webhook](../notifications/webhooks.md) to
send each new item to it.

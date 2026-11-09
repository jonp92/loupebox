# Answers by email

When a person answers a [reply](replies.md), their answer can appear in the conversation on the feedback
item, next to your replies and notes. It is off until you give Loupebox a mailbox to read.

## How it works

Loupebox sends each reply with a **Reply-To** such as `replies+<code>@example.com`. The code names the
feedback item, so when the person answers, their mail client writes to that address. The worker reads the
mailbox over IMAP every minute and adds the answer to the item. It is marked **Customer** and the item goes
back to unread.

* Only the person who wrote the feedback can answer. Mail from any other address is dropped, even with the code.
* The quoted thread under their answer is cut off. Answers over 5000 characters are shortened.
* Out-of-office and other automatic replies are ignored.
* A delivery failure that arrives in the same mailbox marks your reply as **Failed** ("Bounced (5.1.1)").
  Bounces go to the sender address of the outgoing mail, so use the same mailbox as `NOTIFY_SENDER_EMAIL`
  or forward bounces to it.
* Attachments are not kept.
* Webhook channels can subscribe to `feedback.customer_replied`. It carries ids and the length, never the text.

## Set it up

You need a mailbox that accepts **plus-addressing** (`replies+anything@example.com` lands in
`replies@example.com`). Gmail, Fastmail, Microsoft 365 and most hosts do. Then, as a superadmin, open
**System** and fill in the **Inbound email** group, or set these in `.env`:

```
INBOUND_ADDRESS=replies@example.com
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_SECURITY=ssl               # ssl (993), starttls (143) or none
IMAP_USERNAME=replies@example.com
IMAP_PASSWORD=...
```

`INBOUND_ADDRESS` is up to 18 characters before the `@`, with no `+`. `IMAP_SECURITY=none` never sends the
username and password. The worker (`python -m app.worker`) must be running. Messages over
`INBOUND_MAX_BYTES` (256 KB) are skipped.

Reply mail only changes when both an address and a reader are set. Until then, **Reply-To** stays your own
address, as before.

## Checking it works

**System > Status** has an **Inbound email** row, for example:

> Last read just now, last stored 2h ago, 4 emails matched, 2 unmatched, 1 bounced in 24 h

*Matched* answers were added to a conversation. *Unmatched* mail reached the mailbox but belonged to no
conversation (or came from someone else). *Bounced* are delivery failures. *Ignored* are automatic replies,
spam and empty mail. Only the kinds that happened in the last 24 hours are listed. If the worker cannot read the
mailbox, the row shows the error instead (a wrong password, an unreachable host).

It goes to **Attention** when the mailbox has not been read for a few poll intervals (usually a stopped worker),
or when three or more emails were unmatched in the last day and none matched. The usual cause is a mail host
that removes the `+code` from the address, so check that it keeps plus-addressing.

## Limits

Loupebox reads mail; it does not delete it. Processed messages are marked read, so leave the mailbox's own
retention to your mail host.

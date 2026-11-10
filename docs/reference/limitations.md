# Known limits

Loupebox is alpha software. These are the limits to know about today.

* **More than one API container needs Redis.** Rate limits live in the API's memory unless `REDIS_URL` is
  set. See [More than one API container](../install/production.md#more-than-one-api-container).
* **Local image storage needs one shared disk.** With the default storage every API container and the worker
  must see the same folder; an S3 bucket removes that. See [Image storage](../install/image-storage.md).
* **Answers by email need a mailbox.** Loupebox reads a person's answer to a reply over IMAP, and only after you
  set `INBOUND_ADDRESS` and a mailbox. IMAP is the only source so far, and attachments in answers are not kept.
  Until it is set up, replies are one way. See [Answers by email](../manage/inbound-email.md).
* **Capacity is not published.** A first benchmark exists in the repository (`bench/`), but its figures are
  single runs and have not been repeated, so no numbers are promised yet. Loupebox is meant for small sites and
  tools.
* **Not a help desk.** There are no tickets, queues or response-time targets, and none are planned.
* **Breaking changes can happen** between 0.x releases. Read the
  [changelog](https://github.com/jonp92/loupebox/blob/master/CHANGELOG.md) and
  [back up](../install/backups-upgrades.md) before you upgrade.

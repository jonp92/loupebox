# Retention and personal data

Site admins can limit how long a site keeps what visitors send, and can find, export or erase the personal
data held for one email address. Both are on the site's **Settings** page.

## Retention

Under **Data retention** set either or both of:

* **Delete feedback after** a number of days. The message goes, along with its replies, notes, tags and images.
* **Remove emails after** a number of days. The email address is removed and the message, name and
  everything else are kept until the feedback is deleted. This cannot be longer than the delete period.

An empty box keeps that data forever, which is the default. Days count from the day the message arrived.
Changing the number applies to existing messages too, so shortening it deletes the older ones at the next
sweep.

* The worker applies the rules once an hour, and once when it starts. **Nothing is removed unless the worker is
  running.**
* A large backlog is cleared in batches, so turning a rule on for a site with a lot of old feedback does not
  lock the database.
* Alerts keep their own copy of the name, address and first 500 characters of each message (see
  `NOTIFY_RETENTION_DAYS`). Sent and failed alerts for the site are also deleted once they are older than the
  shorter of its two rules. Alerts that have not been sent yet are kept until they go out.
* Each sweep that removes something adds one entry to the [audit log](../security/audit-log.md), made by
  `system`, with the number of messages deleted and addresses removed.
* Deleted messages cannot be restored, except from a [backup](../install/backups-upgrades.md). Old backups
  keep the data until they are themselves removed.

Not covered: the IP address is stored only as a one-way hash, and the browser's user agent and any page
details sent with a message stay with the message until it is deleted.

## Export or erase personal data

Under **Export or erase personal data**, enter an email address and choose **Look up**. The address matches regardless of
upper or lower case, and spam is included. You can then:

* **Export** (a zip file, `person-export.zip`): `data.json` with every message from that address (name, page, tags,
  replies sent to them and internal notes), and an `images` folder with the pictures they sent, one folder per
  message. Each image in `data.json` has a `file` that points to its place in the zip. If the zip would pass
  `PERSON_EXPORT_MAX_BYTES` (500 MB), the remaining pictures are listed in `data.json` with a `note` instead of a
  `file`, as is one whose file has gone missing from storage.
* **Erase**: removes those messages with their replies, notes, tags and images, and the alerts that carry
  their address. This cannot be undone.

Only admins of the site can do this. Each export and erase is recorded in the audit log with the number of
messages (and, for an export, pictures), never the address. The address is sent in the request body, not in the URL, so it stays out of
access logs.

An address someone typed differently (a different spelling, a plus tag) is a different address, so look up
each form you need. Once retention has removed an address, its messages can no longer be found by it.

The API addresses are `POST /v1/api/sites/{id}/privacy/lookup`, `/export` and `/erase`, each with
`{"email": "..."}`. Retention is `retention_delete_days` and `retention_strip_email_days` on
`PATCH /v1/api/sites/{id}` (`null` turns a rule off).

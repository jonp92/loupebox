# Audit log

Superadmins can open **Audit** in the top bar to see who changed what, when, and on which site.

![The audit log](../images/audit-dark.png#only-dark)
![The audit log](../images/audit-light.png#only-light)

## What is recorded

* Users: created, changed, promoted, demoted, enabled, disabled, password reset, picture changed.
* Sites: created, changed, key rotated, deleted.
* Members: added, role changed, removed.
* Notification channels: created, changed, deleted. Webhook secret changes.
* Feedback: deletions (single and bulk), assignment, tag and note-deletion changes, replies, CSV exports.
* Accounts: people changing their own password or two-factor settings, resetting a password by email, and
  signing in with a recovery code.
* Privacy: exports and erasures of personal data (counts only), and each retention sweep (made by `system`).

## What is not recorded

* Passwords, API keys, and the notification settings and addresses (only that they changed).
* The text of feedback, notes and replies.
* Status changes while triaging, and ordinary sign-ins.
* Assignments and tags record ids and tag names only.

## How it behaves

* Each entry is saved in the same database transaction as the change. If the change fails, no entry is left, and
  there is never an entry for something that did not happen.
* The actor's email, the site name and a plain summary are stored as they were at the time, so the history
  still reads well after renames and deletions.
* The worker deletes entries older than `AUDIT_RETENTION_DAYS` (default 365). Set it to `0` to keep everything.
* The API cannot edit or delete entries, but someone with direct access to the database can. If you need proof
  that the log has not been changed, copy it somewhere else.

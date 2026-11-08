# Triage

Open a site and choose **Feedback** to see its inbox.

![The feedback list](../images/feedback-list-dark.png#only-dark)
![The feedback list](../images/feedback-list-light.png#only-light)

## The inbox across all sites

If you are on more than one site (or you are a superadmin), **Inbox** in the sidebar lists the feedback of every
site you can see, newest first, each item labelled with its site. It has the same filters as a site's list, plus a
**Site** filter, and the tabs **All**, **Unread**, **My work** and **Unassigned**. The tag, issue type and assignee
filters appear once you pick a single site, because they belong to one site.

You can change an item's status or assign it to yourself from the inbox, one at a time or for several at once.
Only items on sites where you are an editor or admin can be changed; the rest show no checkbox. To tag, assign to
someone else, delete or export, open the site's own list.

API: `GET /v1/api/inbox` takes the same filters as a site's list plus `site_id`; `GET /v1/api/inbox/counts` gives the
tab counts; `POST /v1/api/inbox/bulk` takes `{ids, action}` where action is `set_status` (with `status`), `assign_me`
or `unassign`, and skips items you may not change.

## Filters

You can narrow the list by:

* status
* search text
* issue type (bug, idea, question, praise or your own)
* rating
* whether the person left an email address
* a date range

Dates are whole days in UTC. The same filters work in the API as query parameters:
`GET /v1/api/sites/{id}/feedback?status=&q=&issue_type=&rating=&has_email=&created_from=&created_to=`,
with dates written `YYYY-MM-DD`.

## Open an item

Choose an item to see the full message, who sent it, the page it came from, the notes and any replies.
Editors can change its status. See [Assign, tag and note](assign-tags-notes.md) and
[Reply to people](replies.md).

![A feedback item](../images/detail-dark.png#only-dark)
![A feedback item](../images/detail-light.png#only-light)

## Bulk actions

Check items, or choose **Select all on this page**, then change their status, assign them, tag them or
delete them in one step. Editors can change status, assign and tag. Only admins can delete.

![Bulk actions on selected items](../images/bulk-dark.png#only-dark)
![Bulk actions on selected items](../images/bulk-light.png#only-light)

In the API, use `POST /v1/api/sites/{id}/feedback/bulk` with one of these bodies:

```json
{ "ids": ["..."], "action": "set_status", "status": "archived" }
{ "ids": ["..."], "action": "delete" }
```

Ids from other sites are skipped. One request takes at most 100 ids (`BULK_MAX_IDS`). A bulk delete is one
entry in the [audit log](../security/audit-log.md), with the ids and the count, never the messages.

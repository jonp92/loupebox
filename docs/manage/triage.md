# Triage

Open a site and choose **Feedback** to see its inbox.

![The feedback list](../images/feedback-list-dark.png#only-dark)
![The feedback list](../images/feedback-list-light.png#only-light)

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

Tick items, or choose **Select all on this page**, then change their status, assign them, tag them or
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

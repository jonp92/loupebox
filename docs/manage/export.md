# Export

Choose **Export CSV** on a site's feedback list to download a CSV copy. All currently set filters will be applied before exporting. Any role that can view the site can export.

The columns are: id, created_at (UTC), status, issue_type, rating, name, email, message, page_url, meta, tags
and assignee (the assignee's email).

* Text that a spreadsheet would run as a formula, meaning text that starts with `=`, `+`, `-` or `@`, gets
  an apostrophe in front so it opens as plain text.
* Notes are never included.
* A download stops at 100,000 rows (`EXPORT_MAX_ROWS`).
* Each export is recorded in the [audit log](../security/audit-log.md) with who exported and how many rows,
  not the contents.

The API address is `GET /v1/api/sites/{id}/feedback/export.csv`, and it takes the same query parameters as the
list.

# Public API

Feedback is sent with one request:

```
POST https://feedback.example.com/v1/api/feedback
Content-Type: application/json
X-API-Key: pk_...
```

```json
{ "message": "The export button is hard to find.", "rating": 4, "email": "sam@example.org" }
```

| Field | Required | Notes |
|---|---|---|
| `message` | yes | 1 to 5000 characters |
| `rating` | no | whole number, 1 to 5 |
| `name` | no | up to 120 characters |
| `email` | no | a valid address |
| `page_url` | no | must start with `http://` or `https://` |
| `metadata` | no | small JSON object of your own details |
| `website` | no | the honeypot field. Leave it empty. |

The request must come from a browser on one of the site's allowed origins. For the full list of fields,
answers and errors, and a ready-made example, see [Your own form](own-form.md). A complete page is in
[`examples/static-site.html`](https://github.com/jonp92/loupebox/blob/master/examples/static-site.html).

## Everything else

The admin app uses the same API under `/v1/api`. When `ENVIRONMENT` is set to `development`, the server shows
interactive documentation for every route at `/v1/api/docs`.

Some useful calls:

* `GET /sites/{id}/feedback` lists feedback. See [Triage](../manage/triage.md#filters) for the filters.
* `POST /sites/{id}/feedback/bulk` update many items at once. See [Triage](../manage/triage.md#bulk-actions).
* `GET /sites/{id}/feedback/export.csv` download a CSV. See [Export](../manage/export.md).

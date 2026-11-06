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

## Sending images

Only for sites that have [images turned on](../manage/images.md). Ask what the site accepts:

```
GET https://feedback.example.com/v1/api/feedback/config
X-API-Key: pk_...
```

```json
{ "attachments": { "enabled": true, "max_count": 3, "max_bytes": 5242880, "max_edge": 2048 } }
```

`enabled` is `false` for a site that takes no images. To send images, post a multipart form to a different
address, with the same JSON as above in a part named `payload` and each image in a part named `images`:

```
POST https://feedback.example.com/v1/api/feedback/with-images
Content-Type: multipart/form-data
X-API-Key: pk_...
```

```bash
curl https://feedback.example.com/v1/api/feedback/with-images \
  -H "X-API-Key: pk_..." -H "Origin: https://www.example.com" \
  -F 'payload={"message":"The button is cut off."}' \
  -F 'images=@screenshot.png'
```

The answer, the origin checks, the honeypot, the challenge and the rate limits are the same as for `/feedback`.
Errors you may see besides those: `403` when the site takes no images, `411` with no `Content-Length`, `413` when
the request is larger than the limits allow, and `422` with a `loc` of `["body", "images", 0]` (the position of
the file) when an image is refused. The JSON endpoint is unchanged, so existing clients need nothing.

## Everything else

The admin app uses the same API under `/v1/api`. When `ENVIRONMENT` is set to `development`, the Swagger UI is available for every route at `/v1/api/docs`.

Some useful calls:

* `GET /sites/{id}/feedback` lists feedback. See [Triage](../manage/triage.md#filters) for the filters.
* `POST /sites/{id}/feedback/bulk` update many items at once. See [Triage](../manage/triage.md#bulk-actions).
* `GET /sites/{id}/feedback/export.csv` download a CSV. See [Export](../manage/export.md).

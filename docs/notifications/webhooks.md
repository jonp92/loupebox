# Webhooks

A **Webhook** notification channel POSTs each event as signed JSON to a URL you control. Add one under
a site's **Notifications** tab. When you create it, Loupebox shows the signing secret (`whsec_...`)
**once**; copy it then. If you lose it, use **Rotate secret** (the old one stops working at once).

Unlike email channels, webhooks are not rate limited or rolled into summaries: every event is sent.

## Request

```
POST <your url>
content-type: application/json
webhook-id: 5b7e0c52-...            same for every retry of the same event: use it to dedupe
webhook-timestamp: 1793577600       unix seconds, set on each attempt
webhook-signature: v1,K5oZ...       base64 HMAC-SHA256, see below
```

```json
{
  "id": "5b7e0c52-...",
  "type": "feedback.created",
  "created_at": "2026-11-02T10:00:00+00:00",
  "site": { "id": "...", "name": "Shop" },
  "data": {
    "feedback_id": "...", "excerpt": "Love it", "rating": 5,
    "name": "Ada", "email": "ada@example.com", "page_url": "https://shop.example.com/p/1",
    "url": "https://loupebox.example.com/sites/.../feedback/..."
  }
}
```

`type` is `feedback.created` (`data` as above; `url` is null unless `PUBLIC_URL` is set), or `test`, which
is what **Send test** posts (`data.message`). The message text is cut to 500 characters and includes whatever the submitter typed, so treat it as untrusted input.

The scheme is [Standard Webhooks](https://www.standardwebhooks.com/), so any library for it works.

## Verifying

Sign `"{webhook-id}.{webhook-timestamp}.{raw body}"` with HMAC-SHA256, keyed with the base64-decoded part
of the secret after `whsec_`. Compare against the `v1,` value in constant time, and reject old timestamps
(5 minutes is typical) so a captured request can't be replayed. Use the **raw** body bytes, not re-serialised JSON.

Python:

```python
import base64, hashlib, hmac, time


def verify(secret: str, headers: dict, body: bytes, tolerance: int = 300) -> None:
    msg_id, ts = headers["webhook-id"], headers["webhook-timestamp"]
    if abs(time.time() - int(ts)) > tolerance:
        raise ValueError("timestamp outside tolerance")
    key = base64.b64decode(secret.removeprefix("whsec_"))
    mac = hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    candidates = [s[3:] for s in headers["webhook-signature"].split() if s.startswith("v1,")]
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise ValueError("bad signature")
```

Node:

```js
import crypto from "node:crypto";

export function verify(secret, headers, body /* Buffer */, toleranceSeconds = 300) {
  const id = headers["webhook-id"], ts = headers["webhook-timestamp"];
  if (Math.abs(Date.now() / 1000 - Number(ts)) > toleranceSeconds) throw new Error("timestamp outside tolerance");
  const key = Buffer.from(secret.replace(/^whsec_/, ""), "base64");
  const expected = crypto.createHmac("sha256", key).update(`${id}.${ts}.`).update(body).digest();
  const ok = headers["webhook-signature"].split(" ").some((s) => {
    if (!s.startsWith("v1,")) return false;
    const got = Buffer.from(s.slice(3), "base64");
    return got.length === expected.length && crypto.timingSafeEqual(got, expected);
  });
  if (!ok) throw new Error("bad signature");
}
```

## Delivery

* A `2xx` response is success. Respond quickly (the timeout is 10 seconds) and do the work afterwards.
* `408`, `425`, `429`, `5xx`, timeouts and connection errors are retried (30 s, 2 min, 10 min, 1 h, 6 h), then
  marked failed. Delivery is **at least once**: use `webhook-id` to ignore repeats.
* Other `4xx` responses fail immediately. **Redirects are not followed** (a `3xx` fails with a hint to use the
  final URL). The response body is never read.
* The delivery log on the Notifications tab shows each attempt's outcome (status code or error, never the body).

## What targets are allowed

The URL must be `https://` and resolve to a **public** address. Private, loopback, link-local, carrier-NAT and
cloud-metadata addresses are refused, both when you save the channel and again on every delivery (after DNS
resolution, connecting to the address that was checked), so a hostname that later points inside your network is
blocked. URLs with a username or password are refused, and `HTTP_PROXY`-style environment variables are ignored.

To send to a receiver on your own network (an internal n8n, a service on the same Docker network), the operator
can set `WEBHOOK_ALLOW_PRIVATE=true`. That also allows plain `http://`, and applies to every site, so only turn it
on if every site admin is trusted to point at internal services.

## Server settings

| Variable | Meaning |
|----------|---------|
| `WEBHOOK_ENCRYPTION_KEY` | Encrypts signing secrets in the database. Falls back to `JWT_SECRET`, but then rotating `JWT_SECRET` makes every secret unreadable and deliveries fail until the secrets are rotated. Set it once and keep it. |
| `WEBHOOK_ALLOW_PRIVATE` | `true` allows private, loopback and plain-http targets. Default `false`. |

# Add a Ganymede feedback form to an app

You are helping add a feedback form to an existing app. The form submits to **Ganymede**, a
separate feedback API server that already exists and is running. You do **not** build or change the
server. You build the form (UI + a small submit function) inside this app.

## Get these from the user first

| Needed | Example | Notes |
|---|---|---|
| `GANYMEDE_URL` | `https://feedback.pressler.tech/v1/api` | Base URL of the API **including the `/v1/api` prefix**, no trailing slash |
| `GANYMEDE_KEY` | `pk_...` | The site's **public** key. Safe to ship in client JS. |
| This app's origin(s) | `https://app.example.com`, `http://localhost:3000` | Each must be on the site's **allowed origins** list in the Ganymede admin UI (Site → Settings). Ask the user to confirm, including local dev origins. |

If the user doesn't have a key yet: a Ganymede **superadmin** creates a site in the admin UI
(Sites → New site) and lists this app's origins. The key is shown on the site's Settings tab.

Put the URL and key in this app's normal config/env mechanism (e.g. `VITE_GANYMEDE_URL`,
`NEXT_PUBLIC_GANYMEDE_KEY`). Never hard-code the production key into shared example code.

## The API contract

```
POST {GANYMEDE_URL}/feedback
Content-Type: application/json
X-API-Key: {GANYMEDE_KEY}
```

Send from the **browser**. The browser adds the `Origin` header automatically, and the server
requires it to match the site's allowed origins. Do not proxy through this app's server unless you
also forward a matching `Origin` header (a proxy usually breaks the check).

### Body

| Field | Required | Rules |
|---|---|---|
| `message` | yes | 1–5000 chars after trimming |
| `rating` | no | integer 1–5 |
| `name` | no | ≤120 chars |
| `email` | no | valid email address |
| `page_url` | no | must start with `http://` or `https://`, ≤2048 chars. Send `location.href`. |
| `metadata` | no | object, ≤20 keys, key ≤64 chars, values string (≤256, longer are cut), number, boolean or null. Good for app version, plan, user id, route. |
| `website` | no | **Honeypot.** Include a visually hidden input named `website` and send its value unchanged (empty for humans). Bots fill it in and are silently dropped. |

**Unknown fields are rejected (422).** Don't add extra top-level fields; use `metadata`.
Total body must be ≤16 KB.

### Responses

| Status | Meaning | What the UI should do |
|---|---|---|
| `201` `{"id": "<uuid>"}` | Accepted (also returned for honeypot drops and for exact duplicates sent within 10 min, so retries are safe) | Show a thank-you, clear the form |
| `403` `{"detail":"Forbidden"}` | Bad/unknown/disabled key, **or origin not allowed**. Deliberately the same message for all. | Generic "couldn't send" message. During setup, check the key and that this origin is in the allowed list. |
| `413` | Body too large | Shouldn't happen; cap `message` at 5000 |
| `422` | Validation failed; `detail` is a list of `{loc, msg}` | Show the field error if you can map `loc`; otherwise generic |
| `429` | Rate limited or daily cap reached; `Retry-After` header (seconds) on rate limits | "Too many submissions, try again later." Don't auto-retry in a loop. |
| network/CORS error | Preflight rejected (origin not allowed) or server unreachable | Generic error; see debugging below |

Server limits (defaults): 10 submissions per IP per minute, 120 per key per minute, plus a daily
cap per site.

## Reference implementation (framework-agnostic)

```ts
export interface FeedbackInput {
  message: string;
  rating?: number;
  name?: string;
  email?: string;
  metadata?: Record<string, string | number | boolean | null>;
  website?: string; // honeypot value, pass through untouched
}

export type SubmitResult =
  | { ok: true }
  | { ok: false; reason: "rate_limited" | "invalid" | "rejected" | "network"; retryAfter?: number };

export async function submitFeedback(input: FeedbackInput): Promise<SubmitResult> {
  let res: Response;
  try {
    res = await fetch(`${GANYMEDE_URL}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": GANYMEDE_KEY },
      body: JSON.stringify({ ...input, page_url: location.href }),
    });
  } catch {
    return { ok: false, reason: "network" };
  }
  if (res.ok) return { ok: true };
  if (res.status === 429) return { ok: false, reason: "rate_limited", retryAfter: Number(res.headers.get("Retry-After")) || undefined };
  if (res.status === 422) return { ok: false, reason: "invalid" };
  return { ok: false, reason: "rejected" };
}
```

Do **not** send `credentials: "include"` and do not send cookies or an `Authorization` header;
this endpoint is anonymous and uses CORS without credentials.

## The form

Match this app's existing UI components and styling. Requirements:

1. A `message` textarea (`required`, `maxLength={5000}`), optional rating (1–5), optional email.
2. A **hidden honeypot input** named `website`: `tabindex="-1"`, `autocomplete="off"`,
   `aria-hidden="true"`, moved off-screen with CSS (not `display:none`, some bots skip those).
   Never label it in a way a screen reader announces.
3. Disable the submit button while sending (prevents double submits; the server also dedupes).
4. Distinct states: idle, sending, success, error, and rate-limited (show the wait if `retryAfter` is known).
5. Accessible: real `<label>`s, error text in an `aria-live`/`role="status"` region, keyboard operable.
6. Treat user text as text. Never insert it as HTML anywhere.
7. Useful `metadata` the user would want triaged with a report (app version, current route, plan);
   **no secrets, tokens or personal data beyond what the user typed**.

Plain-HTML variant, for non-framework pages:

```html
<form id="fb">
  <label>Your feedback <textarea name="message" required maxlength="5000"></textarea></label>
  <label>Email (optional) <input name="email" type="email"></label>
  <input name="website" tabindex="-1" autocomplete="off" aria-hidden="true"
         style="position:absolute;left:-9999px">
  <button>Send</button>
  <p id="fb-status" role="status"></p>
</form>
```

## Verify it works

1. Confirm this app's exact origin (scheme + host + port, e.g. `http://localhost:3000`) is in the
   Ganymede site's allowed origins. **No wildcards, no paths, no trailing slash.**
2. Submit from the running app. Expect `201`. The message should appear in the Ganymede admin UI
   under the site's Feedback tab.
3. Check failure paths: wrong key → `403`; empty message → client-side block (and `422` if bypassed);
   submit the same text twice quickly → one entry, both succeed.
4. Quick server check without the browser (this bypasses origin checks only if the server allows
   missing Origin; by default it does not, so include one):

```bash
curl -i -X POST "$GANYMEDE_URL/feedback" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GANYMEDE_KEY" \
  -H "Origin: http://localhost:3000" \
  -d '{"message":"curl test"}'
```

## Debugging

| Symptom | Likely cause |
|---|---|
| Browser console CORS error, no response | This app's origin isn't on the site's allowed list (preflight returns 403), or the URL is wrong |
| `403 Forbidden` but no CORS error | Wrong/rotated key, site disabled, or origin mismatch (e.g. `http` vs `https`, `www.` vs bare, different port) |
| `422` | A field broke a rule above, or an unknown top-level field was sent |
| `429` immediately in dev | Many test submissions from one IP within a minute; wait for `Retry-After` |
| Submissions succeed but don't appear | They may have been quarantined (many links in the message → status `spam`, hidden by default; filter by status "spam") or the honeypot was filled |

## Don'ts

- Don't add a server-side proxy "to hide the key". The key is public by design; origin checks and
  rate limits protect it. A proxy usually breaks the origin check.
- Don't retry automatically on `403`, `422` or `429`.
- Don't invent extra endpoints or fields. This integration only uses `POST {GANYMEDE_URL}/feedback`.
- Don't commit a real production key into code that is shared publicly beyond this app's config.

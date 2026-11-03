# Add a Loupebox feedback form to an app

> **Easiest path: use the widget.** Loupebox serves a ready-made, customizable feedback widget as an ES
> module (floating button or inline form, issue-type badges, bot-protection challenge built in). Two lines
> of JavaScript, no build step. See [WIDGET.md](WIDGET.md). Read on if you are building your own form.

You are helping add a feedback form to an existing app. The form submits to **Loupebox**, a
separate feedback API server that already exists and is running. You do **not** build or change the
server. You build the form (UI + a small submit function) inside this app.

## Get these from the user first

| Needed | Example | Notes |
|---|---|---|
| `LOUPEBOX_URL` | `https://feedback.example.com/v1/api` | Base URL of the API **including the `/v1/api` prefix**, no trailing slash |
| `LOUPEBOX_KEY` | `pk_...` | The site's **public** key. Safe to ship in client JS. |
| This app's origin(s) | `https://app.example.com`, `http://localhost:3000` | Each must be on the site's **allowed origins** list in the Loupebox admin UI (Site → Settings). Ask the user to confirm, including local dev origins. |

### URL format

Every Loupebox route lives under the `/v1/api` prefix, and `LOUPEBOX_URL` includes it:

```
LOUPEBOX_URL = https://feedback.example.com/v1/api        (origin + /v1/api, no trailing slash)
Endpoint     = {LOUPEBOX_URL}/feedback
             = https://feedback.example.com/v1/api/feedback
```

Store `LOUPEBOX_URL` as **one** config value with the prefix included, so the code only ever appends
`/feedback`. Older paths such as `/v1/feedback` and `/api/v1/feedback` **do not exist** and return
`404`; if you see them in notes or old snippets, they are out of date.

If the user doesn't have a key yet: a Loupebox **superadmin** creates a site in the admin UI
(Sites → New site) and lists this app's origins. The key is shown on the site's Settings tab.

Put the URL and key in this app's normal config/env mechanism (e.g. `VITE_LOUPEBOX_URL`,
`NEXT_PUBLIC_LOUPEBOX_KEY`). Never hard-code the production key into shared example code.

## The API contract

```
POST {LOUPEBOX_URL}/feedback
Content-Type: application/json
X-API-Key: {LOUPEBOX_KEY}
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
| `challenge` | only if the site requires one | Proof for the site's bot-protection challenge. Opaque string, see [Challenges](#challenges-bot-protection). |
| `metadata` | no | object, ≤20 keys, key ≤64 chars, values string (≤256, longer are cut), number, boolean or null. Good for app version, plan, user id, route. |
| `website` | no | **Honeypot.** Include a visually hidden input named `website` and send its value unchanged (empty for humans). Bots fill it in and are silently dropped. |

**Unknown fields are rejected (422).** Don't add extra top-level fields; use `metadata`.
Total body must be ≤16 KB.

### Responses

| Status | Meaning | What the UI should do |
|---|---|---|
| `201` `{"id": "<uuid>"}` | Accepted (also returned for honeypot drops and for exact duplicates sent within 10 min, so retries are safe) | Show a thank-you, clear the form |
| `403` `{"detail":"Challenge required"}` or `"Challenge failed"` | The site has bot protection on and the proof was missing, wrong, expired (5 min) or already used | Fetch a fresh challenge, solve it and retry once. See [Challenges](#challenges-bot-protection). |
| `403` `{"detail":"Forbidden"}` | Bad/unknown/disabled key, **or origin not allowed**. Deliberately the same message for all. | Generic "couldn't send" message. During setup, check the key and that this origin is in the allowed list. |
| `404` | Wrong URL (missing `/v1/api`, or an old path like `/v1/feedback`) | Fix `LOUPEBOX_URL`; see debugging below |
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
    res = await fetch(`${LOUPEBOX_URL}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": LOUPEBOX_KEY },
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

## Challenges (bot protection)

The site key is public, so a script can claim to be your site. An admin can turn on a **challenge** for a
site (Site → Settings → Bot protection). Then every submission must carry proof that the sender did a
little work. Sites with it off are unaffected, and `POST /feedback/challenge` then answers `{"mode":"off"}`,
so a client can always call it first and only solve when the mode says so.

Flow (`mode: "pow"`, proof of work):

1. `POST {LOUPEBOX_URL}/feedback/challenge` with the same `X-API-Key` header as a normal submission
   (no body). Response: `{"mode":"pow","algorithm":"sha256","token":"…","bits":16}`.
2. Find a number `n` so that `sha256("<token>:<n>")` starts with at least `bits` zero **bits**.
   Average cost is 2^bits hashes: 16 bits is about 0.15 s on a desktop browser; each extra bit doubles it.
3. Send `challenge: "<token>:<n>"` in the normal submission body.

A challenge is single-use and expires after 5 minutes, so fetch it when the user submits (or when the form
opens), not at page load. If the admin raises the difficulty, older tokens are rejected: fetch a new one.
Challenge requests have their own limits (30 per IP and 600 per key per minute), separate from submissions.

```ts
// Needs crypto.subtle, which browsers only expose on HTTPS or localhost.
async function solve(token: string, bits: number): Promise<string> {
  const enc = new TextEncoder();
  for (let n = 0; ; n++) {
    const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(`${token}:${n}`)));
    let zeros = 0;
    for (const byte of hash) { if (byte) { zeros += Math.clz32(byte) - 24; break; } zeros += 8; }
    if (zeros >= bits) return `${token}:${n}`;
  }
}

const headers = { "Content-Type": "application/json", "X-API-Key": LOUPEBOX_KEY };
const c = await (await fetch(`${LOUPEBOX_URL}/feedback/challenge`, { method: "POST", headers })).json();
const challenge = c.mode === "pow" ? await solve(c.token, c.bits) : undefined;
await fetch(`${LOUPEBOX_URL}/feedback`, { method: "POST", headers, body: JSON.stringify({ message, challenge }) });
```

Solving blocks nothing (it awaits), but on a big difficulty it is CPU work: show the sending state while it
runs. To keep the page responsive at 18+ bits, run the loop in a Web Worker.

**Plain `http://` pages** (a dev server on a LAN address, say) have no `crypto.subtle`. Use this pure-JS
SHA-256 instead: the same loop, with `sha256(enc.encode(...))` replacing the `crypto.subtle.digest` call
(synchronous, so no `await`). It is checked against the platform SHA-256 and runs at a comparable speed.

```js
// Pure-JS SHA-256 for pages where crypto.subtle is unavailable (plain http:// on anything but localhost).
const primes = [];
for (let n = 2; primes.length < 64; n++) if (primes.every((p) => n % p)) primes.push(n);
const frac = (x) => Math.floor((x - Math.floor(x)) * 2 ** 32);
const K = primes.map((p) => frac(Math.cbrt(p)));
const H0 = primes.slice(0, 8).map((p) => frac(Math.sqrt(p)));
const rotr = (x, n) => (x >>> n) | (x << (32 - n));

function sha256(msg) {
  const len = msg.length;
  const padded = new Uint8Array(((len + 9 + 63) >> 6) << 6);
  padded.set(msg);
  padded[len] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 4, len * 8);
  const h = Uint32Array.from(H0), w = new Uint32Array(64);
  for (let o = 0; o < padded.length; o += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(o + i * 4);
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15], b = w[i - 2];
      w[i] = w[i - 16] + (rotr(a, 7) ^ rotr(a, 18) ^ (a >>> 3)) + w[i - 7] + (rotr(b, 17) ^ rotr(b, 19) ^ (b >>> 10));
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
      const t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    [a, b, c, d, e, f, g, hh].forEach((x, i) => (h[i] += x));
  }
  const out = new Uint8Array(32), ov = new DataView(out.buffer);
  h.forEach((x, i) => ov.setUint32(i * 4, x));
  return out;
}
```

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

1. Confirm the URL is right: `curl "$LOUPEBOX_URL/health"` must return `{"status":"ok"}`. If it
   returns HTML, `404`, or another JSON shape, `LOUPEBOX_URL` is wrong or the server is down.
2. Confirm this app's exact origin (scheme + host + port, e.g. `http://localhost:3000`) is in the
   Loupebox site's allowed origins. **No wildcards, no paths, no trailing slash.**
3. Submit from the running app. Expect `201`. The message should appear in the Loupebox admin UI
   under the site's Feedback tab.
4. Check failure paths: wrong key → `403`; empty message → client-side block (and `422` if bypassed);
   submit the same text twice quickly → one entry, both succeed.
5. Quick server check without the browser (this bypasses origin checks only if the server allows
   missing Origin; by default it does not, so include one):

```bash
LOUPEBOX_URL=https://feedback.example.com/v1/api   # includes the prefix
curl -i -X POST "$LOUPEBOX_URL/feedback" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LOUPEBOX_KEY" \
  -H "Origin: http://localhost:3000" \
  -d '{"message":"curl test"}'
```

## Debugging

| Symptom | Likely cause |
|---|---|
| Browser console CORS error, no response | This app's origin isn't on the site's allowed list (preflight returns 403), or the URL is wrong |
| `404`, or an HTML page where JSON was expected | `LOUPEBOX_URL` is missing the `/v1/api` prefix, has a stale path (`/v1/feedback`, `/api/v1/feedback`), or has a trailing slash/typo. Check `{LOUPEBOX_URL}/health` first. A plain-text `Not found` instead of JSON means the request never reached the API (server-side proxy/deploy problem, not this app). |
| `403 Forbidden` but no CORS error | Wrong/rotated key, site disabled, or origin mismatch (e.g. `http` vs `https`, `www.` vs bare, different port) |
| `422` | A field broke a rule above, or an unknown top-level field was sent |
| `429` immediately in dev | Many test submissions from one IP within a minute; wait for `Retry-After` |
| Submissions succeed but don't appear | They may have been quarantined (many links in the message → status `spam`, hidden by default; filter by status "spam") or the honeypot was filled |

## Don'ts

- Don't add a server-side proxy "to hide the key". The key is public by design; origin checks and
  rate limits protect it. A proxy usually breaks the origin check.
- Don't retry automatically on `403`, `422` or `429`.
- Don't invent extra endpoints or fields. This integration only uses `POST {LOUPEBOX_URL}/feedback`.
- Don't commit a real production key into code that is shared publicly beyond this app's config.

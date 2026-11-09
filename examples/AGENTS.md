# AGENTS.md: adding Loupebox feedback to this app

Drop this file into the root of the app that should send feedback to a Loupebox server (or paste it into
your AI assistant's prompt). It tells a coding agent how to add either the **widget** or a **custom form**.
It is a map; the full references are linked below, read them before writing code.

* Widget: https://loupebox.dev/collect/widget/ (source of truth: `docs/collect/widget.md`)
* Your own form: https://loupebox.dev/collect/own-form/ (`docs/collect/own-form.md`)
* Bot protection: `docs/collect/spam-and-bots.md`; public API: `docs/collect/api.md`

## 1. Get these three values first (ask the user if missing)

| Value | Example | Notes |
|---|---|---|
| `LOUPEBOX_URL` | `https://feedback.example.com/v1/api` | API base **including `/v1/api`**, no trailing slash. Keep it as one config value. |
| `LOUPEBOX_KEY` | `pk_...` | The site's **public** key. Safe in client code. Read it from this app's env/config, don't hard-code it. |
| Origins | `https://app.example.com`, `http://localhost:3000` | Each exact origin (scheme + host + port, no wildcard, no path) must be on the site's allowed origins in the Loupebox admin UI (Site > Settings), including local dev. |

No key yet: a Loupebox superadmin creates a site (Sites > New site); the key and a ready-made snippet are on its Settings tab.

## 2. Choose: widget or own form

* **Widget** (default, least code): a dependency-free ES module served by the Loupebox server. Handles the
  honeypot, bot-protection challenges, images, screenshot capture, theming and accessibility.
* **Own form**: only when the user wants full control of the markup or the widget doesn't fit. You still call
  the same public endpoint. For a custom UI on top of the widget's logic, use `createClient()` (section 4).

Never change the Loupebox server for this. Everything below happens in the user's app.

## 3. Widget

Simplest, no JavaScript, works under a strict CSP:

```html
<script type="module" src="https://feedback.example.com/widget/v1/loupebox.js" data-key="pk_..."></script>
```

With options (a bundler project can `import` the same URL, or host a downloaded copy):

```html
<script type="module">
  import { createWidget } from "https://feedback.example.com/widget/v1/loupebox.js";
  const widget = createWidget({
    url: "https://feedback.example.com/v1/api",
    key: "pk_...",
    // everything below is optional
    issueTypes: [{ id: "bug", label: "Something's broken" }, { id: "idea", label: "Idea" }],
    fields: { email: "optional", rating: false },
    extraFields: [{ id: "plan", label: "Your plan", type: "select", options: ["free", "pro"] }],
    metadata: () => ({ route: location.pathname, appVersion: APP_VERSION }),
    launcher: false,              // hide the corner button, open it from your own UI
  });
  document.querySelector("#help").addEventListener("click", () => widget.open());
</script>
```

Customization cheat sheet:

| Goal | Use |
|---|---|
| Position, theme | `position: "bottom-left"`, `theme: "auto" \| "light" \| "dark"` |
| Brand it | `colors`, `radius`, `fontFamily`, `zIndex`, or CSS vars on `loupebox-widget` (`--gm-accent`, `--gm-accent-text`, `--gm-bg`, `--gm-text`, `--gm-muted`, `--gm-border`, `--gm-radius`, `--gm-font`, `--gm-z`) |
| Different button / own trigger | `launcher: false`, then `widget.open()` (or `window.loupebox.open()` with the script tag) |
| Render inline, not floating | `mode: "inline"`, `target: "#feedback"` |
| Wording, translations | `strings` (keys are in `defaultStrings`) |
| Categories | `issueTypes`, `requireIssueType`, `defaultIssueType` (stored as `metadata.issue_type`) |
| Extra questions | `extraFields` (`text`, `textarea`, `select`, `checkbox`), sent in `metadata` |
| Attach context | `metadata` (object or function), `pageUrl` |
| Last-look hook / cancel | `beforeSubmit(payload)` returns the payload or `false` |
| React to events | `widget.on("submit" \| "error" \| "open" \| "close", fn)` |
| Images, screenshot | automatic when the site enables them; `images: false`, `capture: false` to turn off |

Rules for widgets:

* Option names are camelCase in JS and `data-*` kebab-case on the script tag. Only simple options exist as
  `data-*`; `beforeSubmit`, `metadata`, `extraFields`, `strings`, `colors` need `createWidget`.
* Unknown options are ignored with a console warning; a wrong value for a known option throws. Read the console.
* `/widget/v1/` is "latest 1.x" and only ever adds options. To pin, host the file yourself (optionally with an SRI hash).
* CSP: allow the widget script's origin in `script-src` and the API origin in `connect-src` (and `blob:` in `img-src` for image thumbnails).
* `metadata` limits: at most 20 keys, key up to 64 chars, values string (cut at 256), number, boolean or null.
  `issue_type` and `widget_version` are reserved. **No secrets, tokens or personal data.**

## 4. Your own UI, using the widget's client

`createClient` is the widget's transport without any UI. It adds the honeypot, solves challenges, retries once,
supports images, and never throws:

```js
import { createClient } from "https://feedback.example.com/widget/v1/loupebox.js";
const client = createClient({ url: LOUPEBOX_URL, key: LOUPEBOX_KEY });
const r = await client.submit({ message, issueType: "idea", email, metadata: { route: location.pathname } });
if (!r.ok) handle(r.reason, r.retryAfter, r.fields);
// reason: "network" | "rate_limited" | "invalid" | "rejected" | "challenge_unsupported"
```

Prefer this over raw `fetch` unless the user can't import from the Loupebox server.

## 5. Fully custom form with raw `fetch`

```
POST {LOUPEBOX_URL}/feedback
Content-Type: application/json
X-API-Key: {LOUPEBOX_KEY}
```

| Field | Rules |
|---|---|
| `message` | required, 1 to 5000 chars |
| `rating` | optional integer 1 to 5 |
| `name` | optional, up to 120 |
| `email` | optional, valid address |
| `page_url` | optional, `http(s)://`, up to 2048; send `location.href` |
| `metadata` | optional object, limits as above |
| `website` | **honeypot**: a hidden input named `website`; send its value untouched (empty for humans) |
| `challenge` | only when the site has bot protection on, see `docs/collect/own-form.md` |

* **Unknown top-level fields are rejected (422).** Put extras in `metadata`. Body at most 16 KB.
* Send from the **browser** with no `credentials`, cookies or `Authorization`. The browser's `Origin` header is what the server checks.
* Responses: `201 {"id"}` success (also for honeypot drops and duplicates, so retries are safe); `403 Forbidden`
  bad key or origin; `403 Challenge required/failed` fetch a fresh challenge and retry once; `404` wrong URL
  (missing `/v1/api`); `422` validation, `detail` is `[{loc, msg}]`; `429` rate limited, honor `Retry-After`;
  `503` busy, retry once after `Retry-After`.
* Images use `POST {LOUPEBOX_URL}/feedback/with-images` (multipart); see `docs/collect/api.md`. Ask the site's
  limits with `GET {LOUPEBOX_URL}/feedback/config`.

Form requirements:

1. `message` textarea (`required`, `maxLength=5000`), optional rating and email.
2. Honeypot input `website`: `tabindex="-1"`, `autocomplete="off"`, `aria-hidden="true"`, moved off-screen with
   CSS (not `display:none`), never labeled for screen readers.
3. Disable submit while sending. Distinct states: idle, sending, success, error, rate-limited (show the wait).
4. Real `<label>`s, errors in a `role="status"` / `aria-live` region, keyboard operable, controls at least 44px
   on touch screens. Match the app's existing components and styling.
5. Render visitor text as text, never as HTML.

## 6. Verify

1. `curl "$LOUPEBOX_URL/health"` returns `{"status":"ok"}`. HTML or a 404 means the URL is wrong.
2. Submit from the running app (not only curl). Expect `201`, and the item appears under the site's Feedback tab.
3. Server-side smoke test (include an Origin, the server rejects requests without one by default):
   ```bash
   curl -i -X POST "$LOUPEBOX_URL/feedback" -H "Content-Type: application/json" \
     -H "X-API-Key: $LOUPEBOX_KEY" -H "Origin: http://localhost:3000" -d '{"message":"curl test"}'
   ```
4. Failure paths: wrong key gives `403`; empty message is blocked in the client; the same text twice quickly yields one entry.

| Symptom | Likely cause |
|---|---|
| CORS error, no response | This origin isn't on the allowed list, or the URL is wrong |
| `403` without a CORS error | Wrong or rotated key, site disabled, or origin mismatch (`http` vs `https`, `www.`, port) |
| `404` or HTML instead of JSON | `LOUPEBOX_URL` lacks `/v1/api`, has a stale path (`/v1/feedback`), or a trailing slash |
| `429` right away in dev | Several test submissions within a minute; wait for `Retry-After` |
| Sent but not visible | Quarantined as spam (many links) or honeypot filled; filter by status "spam" |

## Don'ts

* Don't add a server-side proxy to "hide the key": the key is public by design, a proxy breaks the origin check.
* Don't retry automatically on `403`, `422` or `429`, and don't loop on `503`.
* Don't invent endpoints or fields; the public surface is `/feedback`, `/feedback/with-images`, `/feedback/config`, `/feedback/challenge`.
* Don't try to restyle the widget's internals; it lives in a shadow root. Theme it with the options or the `--gm-*` variables.
* Don't commit a production key into code that is shared publicly beyond this app's config.

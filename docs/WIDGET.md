# Feedback widget

A small, dependency-free ES module that adds a feedback button (or an inline form) to any page. Visitors
can tag what kind of feedback it is with **issue-type badges** (bug, idea, question, praise by default),
and the choice arrives with the feedback as `metadata.issue_type`.

It talks to the same public endpoint as a hand-built form (see [CLIENT_INTEGRATION.md](CLIENT_INTEGRATION.md)),
including origin checks, the honeypot and the bot-protection challenge, so there is nothing extra to configure
on the server. The snippet for your site, with its key filled in, is on **Site → Settings → Feedback widget**.

## Quick start

```html
<script type="module">
  import { createWidget } from "https://feedback.example.com/widget/v1/ganymede.js";

  createWidget({
    url: "https://feedback.example.com/v1/api",   // the API base URL, including /v1/api
    key: "pk_...",                                 // the site's public key
  });
</script>
```

The page's origin (scheme + host + port) must be in the site's **allowed origins**. In a bundler project the
same module works as an import (`import { createWidget } from "https://.../ganymede.js"`) or, for no network
dependency, download the file and import it locally.

## Options

Everything except `url` and `key` is optional.

| Option | Default | Meaning |
|---|---|---|
| `url`, `key` | required | API base URL (with `/v1/api`) and the site's public key |
| `mode` | `"floating"` | `"floating"` (button + panel) or `"inline"` (the form is rendered inside `target`) |
| `target` | | Inline mode: an element or CSS selector to render into |
| `position` | `"bottom-right"` | or `"bottom-left"` |
| `launcher` | `true` | `false` hides the button; open it yourself with `widget.open()` |
| `issueTypes` | bug, idea, question, praise | The badges: `[{ id, label, icon?, color? }]`, or `false` for none |
| `defaultIssueType` | none | Id of a badge selected from the start |
| `requireIssueType` | `false` | Make choosing a badge mandatory (it then can't be un-selected) |
| `fields` | `{ rating: false, name: false, email: "optional" }` | `rating` is a boolean; `name` and `email` are `false`, `"optional"` or `"required"` |
| `extraFields` | `[]` | Your own fields, sent in `metadata` (see below) |
| `metadata` | | An object, or a function called at submit time, merged into `metadata` |
| `pageUrl` | `location.href` | Page URL to report, or a function returning one |
| `theme` | `"auto"` | `"auto"` follows the visitor's light/dark setting, or force `"light"` / `"dark"` |
| `colors` | | `accent`, `accentText`, `background`, `text`, `muted`, `border` (any CSS color) |
| `radius`, `fontFamily`, `zIndex` | | Corner radius in px, a font stack, and the stacking order |
| `strings` | English | Override any text (see `defaultStrings` for the keys), e.g. to translate |
| `closeDelay` | `2500` | Milliseconds before the panel closes after sending; `0` keeps it open |
| `beforeSubmit` | | `(payload) => payload \| false`, may be async: last look, change it or cancel |

### Issue-type badges

```js
createWidget({
  url, key,
  issueTypes: [
    { id: "bug", label: "Something's broken", color: "#d64545" },
    { id: "billing", label: "Billing", icon: "💳" },
    { id: "idea", label: "Idea" },
  ],
  requireIssueType: true,
});
```

* `id` is what is stored: lowercase letters, digits, `-` and `_`, up to 32 characters. `label` is what the
  visitor sees (up to 40 characters). Both are rendered as text, never as HTML.
* The four default types have drawn icons; for your own, `icon` is a short text icon such as an emoji.
* In the admin UI the type shows as a badge on each item and as a filter on the feedback list, it is a column in
  the CSV export, and it is included in notification emails and webhook payloads (`data.issue_type`).
* Only plain ids are shown or exported as a type; anything else a client puts in `metadata.issue_type` is ignored.

### Extra fields

```js
createWidget({
  url, key,
  extraFields: [
    { id: "plan", label: "Your plan", type: "select", options: ["free", "pro"], required: true },
    { id: "contact_ok", label: "You may contact me", type: "checkbox" },
  ],
});
```

Types: `text` (default), `textarea`, `select` (needs `options`), `checkbox`. Values are sent in `metadata` under
the field's `id` (a checkbox sends `true`/`false`). Ids can't be `issue_type` or `widget_version`.

### Metadata

Every submission carries `metadata.widget_version` and, when chosen, `metadata.issue_type`. Yours is merged in
(`metadata` option, then extra fields); it can't overwrite those two. The server allows at most 20 keys, keys up to
64 characters and values that are strings (cut at 256), numbers, booleans or null. **Don't put secrets or tokens in it.**

## Controlling it from the page

`createWidget()` returns a controller:

```js
const widget = createWidget({ url, key, launcher: false });

document.querySelector("#help").addEventListener("click", () => widget.open());

const stop = widget.on("submit", ({ id, payload }) => analytics.track("feedback", { type: payload.issueType }));
widget.on("error", ({ reason, retryAfter }) => console.warn(reason, retryAfter));
// "open" and "close" events too. stop() removes a listener.

widget.update({ theme: "dark", strings: { title: "Tell us more" } });  // rebuilds the form (typed text is cleared)
widget.close();
widget.destroy();                                                         // removes it from the page
```

`widget.isOpen`, `widget.element` (the `<ganymede-widget>` element) and `widget.supports("issue-types")` are also available.

## Look and feel

The widget lives in a shadow root, so your CSS can't break it and it can't leak into your page. Colors are CSS
custom properties on the `ganymede-widget` element, so you can theme it from your own stylesheet:

```css
ganymede-widget {
  --gm-accent: #0a7d5a;     --gm-accent-text: #fff;
  --gm-bg: #fff;            --gm-text: #111;       --gm-muted: #667;   --gm-border: #dde;
  --gm-radius: 8px;         --gm-font: "Inter", sans-serif;           --gm-z: 5000;
}
```

The `colors`, `radius`, `fontFamily` and `zIndex` options set the same properties. It styles itself without inline
`style` attributes or injected scripts, so it works under a strict Content-Security-Policy (the page only needs to
allow the module script's origin in `script-src`, and the API origin in `connect-src`). Keyboard use, focus handling, `Escape` to close,
screen-reader labels and `prefers-reduced-motion` are built in; on narrow screens the panel becomes a bottom sheet.

## Your own UI

Don't want the built-in form? Use the same client without any UI:

```js
import { createClient } from "https://feedback.example.com/widget/v1/ganymede.js";

const client = createClient({ url, key });
const result = await client.submit({ message: "Hi", issueType: "idea", email: "a@b.co", metadata: { route: "/x" } });
if (!result.ok) console.log(result.reason, result.retryAfter, result.fields);
// reason: "network" | "rate_limited" | "invalid" | "rejected" | "challenge_unsupported"
```

It adds the honeypot field, fetches and solves the site's challenge when one is on, retries once with a fresh
challenge if the proof was rejected, and never throws.

## Bot protection

If the site has a challenge enabled (Site → Settings → Bot protection), the widget handles it: it asks for a
challenge on every submission, solves the proof of work in small slices so the page stays responsive (using the
built-in crypto where available and a pure-JS SHA-256 on plain `http://` pages), and sends the proof. A challenge
kind this version doesn't understand is reported ("needs a newer widget") rather than skipped.

## Versioning and upgrades

* `/widget/v1/ganymede.js` is **the latest 1.x**. Within v1, releases only add optional options, events, exports
  and capabilities, so you pick up fixes and features without changing anything. Breaking changes ship as
  `/widget/v2/` and v1 keeps working until you move.
* Options a page sets that this version doesn't know are **ignored with a console warning**, and a wrong value for
  a known option throws a clear error. So config written for a newer widget still works on an older cached one.
* Feature-detect with `capabilities` (exported) or `widget.supports("name")`. `VERSION` is exported, and every
  submission reports it as `metadata.widget_version`, so you can see which versions are in the wild.
* The file is cached for 5 minutes (with a day of stale-while-revalidate). To freeze a version, download the file,
  host it yourself and, if you like, add a Subresource Integrity hash.

## Build and test (contributors)

Source is TypeScript in `web/widget/src` (one small module per concern). `npm run build` in `web/` builds the
admin app and the widget (`dist/widget/v1/ganymede.js`, about 11 kB gzipped, plus type declarations in
`dist/widget/v1/types/`). `npm test` rebuilds the widget and runs its tests against the built file, using
Node's test runner and jsdom. The web Docker image serves it with the CORS headers browsers need for module
scripts. When adding a feature: add an optional option (give it a default in `options.ts`), add a `capabilities`
entry, document it here, and keep the v1 promise above.

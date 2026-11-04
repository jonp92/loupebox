# Spam and bots

Anyone on the internet can post to the public feedback address, so Loupebox checks every submission in
several layers. Most are on without any setup.

| Check | What it does |
|---|---|
| Allowed origins | The page sending the feedback must be on the site's list. There are no wildcards, and a request with no origin is refused. |
| Rate limits | Limits per visitor address and per site key. Over the limit, the server answers `429` with a `Retry-After` header. Sign-in is limited too. |
| Daily quota | A cap on how many messages one site accepts per day (UTC). |
| Size limits | Bodies over 16 KB are refused. Unknown fields are refused. Text length is capped. `page_url` must start with `http://` or `https://`. |
| Honeypot | A hidden field that real visitors never fill in. If it is filled, the server pretends it worked and stores nothing. |
| Duplicates | The same message and email within 10 minutes returns the first receipt instead of making a second item. |
| Spam quarantine | Messages with many links are stored with the status `spam` and hidden from the default list. |
| Key controls | Rotate a site's key or switch the site off at any time. Every key problem gets the same `403`, so a guess reveals nothing. |
| Privacy | Visitor addresses are stored only as keyed hashes. |

The admin app shows all feedback as plain text, never as HTML, and only turns `http` and `https` addresses
into links.

## Watching the defenses work

Each site has an **Activity** tab, visible to every role. It shows, per day, how many messages were stored,
quarantined or blocked, with a table view. Blocked counts cover honeypot hits, wrong origins, rate limits,
daily-cap hits, failed challenges and duplicates. Requests with an unknown key cannot be matched to a site, so
they are not counted.

![The Activity tab](../images/activity-dark.png#only-dark)
![The Activity tab](../images/activity-light.png#only-light)

## Turn on a challenge

If a site still gets junk, ask visitors' browsers to do a small piece of work before each submission. The
visitor does not see it. Open the site's **Settings** tab, find **Bot protection** and choose a challenge.

* The built-in challenge is a signed, single-use proof of work. The [widget](widget.md) solves it for you.
  If you built your own form, see [the challenge section](own-form.md#challenges-bot-protection).
* It adds a little work for every visitor, so only turn it on if you need it.
* Challenges are pluggable. A developer can add a module in `app/challenges/verifiers/` that registers a
  verifier, for example to check a Turnstile or hCaptcha token.

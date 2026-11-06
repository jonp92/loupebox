# Where to find logs

Loupebox writes its logs to standard output, so Docker collects them. Run these in the folder that holds
`docker-compose.yml`:

```bash
docker compose logs -f api worker      # both, live
docker compose logs --since 1h worker  # the last hour of one service
docker compose logs --tail 100 api     # the last 100 lines
```

The `api` service handles the admin app and incoming feedback. The `worker` service sends the email and
webhook alerts. Alert problems show up in the worker's log. Everything else shows up in the API's log. If
you started the app another way, the same lines go to that process's terminal.

Loupebox does not log feedback text, passwords or tokens.

## Check the Status tab first

Many problems are visible without reading a log. Sign in as a superadmin and open **System**, then
**Status**. It shows:

* whether the database and Redis are reachable,
* when the worker was last seen,
* how many alerts are waiting, held or failed,
* **Recent failures**, with the site, the channel and the error for each failed alert,
* **Finish setting up**, a checklist of what is still missing.

If an alert did not arrive, **Recent failures** usually names the reason. Go to the logs when the Status tab
is not enough, for example when the worker is "Never seen" or you need a stack trace.

## What the lines mean

Each line from the worker looks like this:

```
2026-11-06 16:02:11,402 INFO loupebox.worker: worker started, polling every 5s
```

The third part is the logger name. It tells you which part of Loupebox wrote the line.

| Logger | What it reports |
|---|---|
| `loupebox.worker` | The worker starting and stopping, the hourly clean-up (`purged 12 finished outbox rows`, expired challenge markers, audit events past retention, `retention removed 11 feedback items or addresses`), and `worker pass failed` with a stack trace when a cycle crashes. The worker keeps running and tries again. |
| `loupebox.notifications` | `provider brevo raised` and a stack trace: a notification provider failed in an unexpected way. The alert is retried. An ordinary refusal, such as a rejected address or a webhook that returns an error, is not logged. It is kept with the alert and shown under **Recent failures**. |
| `loupebox.system_mail` | `mail provider smtp raised`: the same, for password reset and other system email. |
| `loupebox.password_reset` | `password reset email for user 12 was not sent`, followed by the reason. The user is identified by number only. |
| `loupebox.settings` | `ignoring saved setting <name>`: a value saved on the System page is no longer valid, so the value from `.env` is used. Also `reloading saved settings failed` in the API. |
| `loupebox.rate_limit` | `Redis unavailable, rate limits are per process for now`. Rate limits keep working but are no longer shared between API containers. The line repeats every few seconds while Redis stays down. See [More than one API container](../install/production.md#more-than-one-api-container). |

## The API log looks different

The worker prints the time, level and logger name. The API does not set up its own log format, so you only
see warnings and errors from Loupebox, and they have no time or logger name. Match them by their wording
using the table above. Docker adds its own time with `docker compose logs -t api`.

The server also logs one line for each request it handles.

## Keep the logs from growing forever

Docker keeps container logs without a size limit by default. To cap them, add this to each service in
`docker-compose.yml`:

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"
```

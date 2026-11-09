# Put it on the internet

The Docker setup only listens on your own machine. To make Loupebox reachable from the internet you need a
domain name and a reverse proxy that handles HTTPS. This page uses [Caddy](https://caddyserver.com), which
gets certificates for you. Any proxy works if it follows the same rule and passes on the original host and client address headers.

Replace `feedback.example.com` below with your own domain.

## How the proxy should route

Every API address starts with `/v1/api`. Send those requests to the API (port 8000) and everything else to
the admin app (port 8080). Do not rewrite paths. By default the admin app and the API share one domain, so the
admin app needs no cross-site settings, and your websites send feedback to
`https://feedback.example.com/v1/api/feedback`.

## Steps

1. Point your domain's DNS at the machine.
2. Create `.env` from the production template. This script writes the file with random secrets:

    ```bash
    curl -fsSLO https://raw.githubusercontent.com/jonp92/loupebox/master/deploy/production.env.example
    sh setup.sh production.env.example
    ```

3. Open `.env` and set your domain in `API_URL`, `ADMIN_ORIGINS` and `PUBLIC_URL`.
4. Start Loupebox and create the first administrator, as in [Install with Docker](docker.md).
5. Add the [Caddyfile from the repository](https://github.com/jonp92/loupebox/blob/master/deploy/Caddyfile)
   to your Caddy setup, with your domain, and reload Caddy. It forwards to `127.0.0.1:8000` and
   `127.0.0.1:8080`.
6. Sign in at your domain, create a site and list your website's origins. Your websites use
   `https://feedback.example.com/v1/api` as the API address.

## Things to know

* Set `TRUST_PROXY=true` so rate limits use the visitor's real address. This is only safe if nobody can
  reach the API port except through the proxy. The default setup keeps it on localhost, do not open it directly to the internet.
* A submission with images can be about 16 MB. Caddy has no request size limit by default; if your proxy has one
  (nginx: `client_max_body_size`), allow at least that much for `/v1/api/feedback/with-images`. The API enforces
  its own limits.
* The admin UI keeps one long-lived response open at `/v1/api/events` (server-sent events) to update itself live.
  Caddy streams it as is. nginx needs `proxy_buffering off;` for that path (the API also sends
  `X-Accel-Buffering: no`) and a `proxy_read_timeout` above 30 seconds; the stream sends a keepalive every 20.
  Without it everything still works, the screens just update on reload. The API's database connection for
  `LISTEN` must be direct or a session-pooled pgbouncer, not transaction pooling.
* A health check is available at `/v1/api/health`.
* The API's Swagger documentation at `/v1/api/docs` is available when `ENVIRONMENT=development`.
* If Caddy runs in a container, put it on the compose network and forward to `api:8000` and `web:8080`.

Before you go live, work through the [production checklist](production.md).

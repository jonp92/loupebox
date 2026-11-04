# Put it on the internet

The Docker setup only listens on your own machine. To make Loupebox reachable from the internet you need a
domain name and a reverse proxy that handles HTTPS. This page uses [Caddy](https://caddyserver.com), which
gets certificates for you. Any proxy works if it follows the same rule.

Replace `feedback.example.com` below with your own domain.

## How the proxy should route

Every API address starts with `/v1/api`. Send those requests to the API (port 8000) and everything else to
the admin app (port 8080). Do not rewrite paths. Because the admin app and the API share one domain, the
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
  reach the API port except through the proxy. The default setup keeps it on localhost, so leave it that way.
* The health check is at `/v1/api/health`.
* The API's interactive documentation at `/v1/api/docs` is switched off when `ENVIRONMENT=production`.
* If Caddy runs in a container, put it on the compose network and forward to `api:8000` and `web:8080`.

Before you go live, work through the [production checklist](production.md).

# Install with Docker

This sets up Loupebox on one machine with Docker Compose. You need Docker with the compose plugin, plus
`openssl` and `curl`.

## Install

Make a folder, download three files, and let the setup script write your settings:

```bash
mkdir loupebox && cd loupebox
for f in docker-compose.yml setup.sh env.example; do
  curl -fsSLO https://github.com/jonp92/loupebox/releases/latest/download/$f
done
sh setup.sh
docker compose up -d
```

`setup.sh` creates a `.env` file with a random password for the database and random secrets for sign-in.
Keep that file private. Do not change the encryption keys later, or people using two-factor sign-in will be
locked out and existing webhooks will stop working.

Then create the first administrator. This account can create sites and other users:

```bash
docker compose run --rm api python -m scripts.create_superadmin you@example.com
```

It asks you to choose a password. Open <http://localhost:8080> and sign in.

## What is running

| Service | What it does |
|---|---|
| `db` | The Postgres database. Your data lives in the `pgdata` volume. See [Backups](backups-upgrades.md) to use a bind mount instead. |
| `migrate` | Updates the database to the current version when the stack starts, then exits. The API waits for it to finish. |
| `api` | The server. Available at `http://localhost:8000/v1/api`. |
| `worker` | Sends email and webhook alerts. Nothing is sent if it is not running. |
| `web` | The React admin app. Available at `http://localhost:8080`. |

The ports are open on your own machine only. To reach Loupebox from the internet, put a reverse proxy in
front of it, as described in [Put it on the internet](reverse-proxy.md).

## Choosing a version

By default you get the newest release. To stay on a specific version, add this to `.env`:

```
LOUPEBOX_VERSION=0.1.0-alpha.6
```

The images are `ghcr.io/jonp92/loupebox-api` and `ghcr.io/jonp92/loupebox-web`, for both Intel and ARM
machines. The worker runs from the API image.

## Changing ports

Set `API_PORT`, `WEB_PORT` or `DB_PORT` in `.env` if a port is already taken. The defaults are 8000, 8080
and 5432. If you use a reverse proxy, change its upstream ports to match.

## Build from source instead

If you cloned the repository, you can build the images yourself:

```bash
./scripts/setup.sh
docker compose up -d --build
docker compose run --rm api python -m scripts.create_superadmin you@example.com
```

See [Develop Loupebox](../reference/development.md) to run the pieces without Docker.

## Next

[First steps](first-steps.md): create your first site and send a test message.

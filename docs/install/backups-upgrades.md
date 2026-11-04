# Backups and upgrades

## Back up

Everything lives in the database, in the `pgdata` volume. To save a copy:

```bash
docker compose exec -T db pg_dump -U ganymede ganymede > loupebox-backup.sql
```

To restore it into an empty database:

```bash
docker compose exec -T db psql -U ganymede ganymede < loupebox-backup.sql
```

Also keep a copy of your `.env` file. Without the encryption keys in it, two-factor secrets and webhook
secrets in a restored database cannot be read.

!!! danger
    `docker compose down -v` deletes the database volume. Leave off `-v` unless you mean it.

## Using a bind vs Docker Volume

By default Docker keeps the data in a volume. Using a bind mount is safer for production use. You can find it, include it in your server's backups or snapshots, and `docker compose down -v` cannot delete it accidentally.

In `docker-compose.yml`, change the `db` service's volume line:

```yaml
    volumes: ["./pgdata:/var/lib/postgresql/data"]
```

Then delete the `pgdata:` entry under `volumes:` at the bottom of the file, and run `docker compose up -d`.

* **Do this on a new install**, before the first start. To move an existing install, make a `pg_dump` backup
  (above), run `docker compose down`, change the file, run `docker compose up -d`, and restore the dump.
* **Copying the folder is only a safe backup while the database is stopped.** A copy taken while Postgres is
  running can be unusable. Run `docker compose stop db` first, or keep using `pg_dump` for backups and treat the
  folder as a second safety net.
* **Use this on a Linux server.** On Docker Desktop for Mac or Windows, a Postgres folder on your own disk can be
  slow or fail on file permissions. A named volume works better there.
* Do not commit the `pgdata` folder to git.

## Upgrade

1. Read the [changelog](https://github.com/jonp92/loupebox/blob/master/CHANGELOG.md) for changes that need
   action from you.
2. Back up the database.
3. Pull the new images and restart:

    ```bash
    docker compose pull && docker compose up -d
    ```

Database changes run by themselves before the API starts. If you pinned a version with `LOUPEBOX_VERSION`,
change it first.

## Roll back

Restore the backup, set `LOUPEBOX_VERSION` in `.env` to the previous version, then pull and start again.
You need the backup because a newer version may have changed the database in a way the older one cannot
read.

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

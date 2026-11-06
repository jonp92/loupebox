# Backups and upgrades

## Back up

Everything lives in the database, except the images visitors attach to feedback, which are files in a Docker
volume. The backup script saves both. Run this in the folder that holds `docker-compose.yml` (in a git checkout,
use `./scripts/backup.sh`), with Loupebox running:

```bash
sh backup.sh
```

It writes one file to `backups/`, named by the date and time in UTC, such as
`backups/loupebox-2026-11-04T031500Z.tar`. The file holds a dump of the database, the image files and a copy of
your `.env`.
It keeps the newest 14 backups and deletes older ones. Set `BACKUP_KEEP` to keep a different number, or `0` to
keep them all. To write somewhere else, give a folder: `sh backup.sh /mnt/backups/loupebox`.

!!! warning
    The backup holds your `.env`, so it holds your database password and encryption keys. Keep it as private as
    the `.env` itself. The keys are in it on purpose: without them, two-factor secrets and webhook secrets in a
    restored database cannot be read.

A backup on the same disk does not survive the disk failing. Copy the `backups` folder to another machine or to
storage you trust.

### Back up every night

Add a line like this with `crontab -e`, changing the folder to yours:

```
15 3 * * * cd /srv/loupebox && sh backup.sh >> backups/backup.log 2>&1
```

## Restore

```bash
sh restore.sh backups/loupebox-2026-11-04T031500Z.tar
```

It asks you to type `yes`, then replaces everything in the database and all the images with the backup and
starts Loupebox again. A backup made before images existed leaves the images as they are.
Add `-y` to skip the question. On a new machine, put `docker-compose.yml`, `restore.sh` and the backup in an
empty folder and run the same command: there is no `.env` yet, so the one from the backup is used.

If you already have a `.env` and it differs from the one in the backup, your `.env` is left alone and the
backup's copy is saved as `.env.from-backup`. Compare the encryption keys in the two files and keep the ones
the backup was made with.

After a restore, Loupebox updates the database to the version you run. To go back to an older version, see
[Roll back](#roll-back).

### Without the scripts

The scripts run these commands for you. To do it by hand:

```bash
docker compose exec -T db pg_dump -U ganymede ganymede > loupebox-backup.sql
docker compose exec -T db psql -U ganymede ganymede < loupebox-backup.sql   # into an empty database
```

Keep a copy of your `.env` next to the dump.

!!! danger
    `docker compose down -v` deletes the database volume. Leave off `-v` unless you mean it.

## Keep the database in a folder

By default Docker keeps the data in a volume. A folder (a bind mount) is safer for production use. You can find
it, include it in your server's backups or snapshots, and `docker compose down -v` cannot delete it by accident.

Add this line to `.env` before the first start:

```bash
DB_DATA_DIR=./pgdata
```

* **Do this on a new install.** To move an existing install, back up, run `docker compose down`, add the line,
  run `docker compose up -d`, then restore the backup.
* **Copying the folder is only a safe backup while the database is stopped.** A copy taken while Postgres is
  running can be unusable. Run `docker compose stop db` first, or keep using `backup.sh` and treat the folder
  as a second safety net.
* **Use this on a Linux server.** On Docker Desktop for Mac or Windows, a Postgres folder on your own disk can be
  slow or fail on file permissions. A named volume works better there.
* Do not commit the `pgdata` folder to git.

## Upgrade

1. Read the [changelog](https://github.com/jonp92/loupebox/blob/master/CHANGELOG.md) for changes that need
   action from you.
2. Back up: `sh backup.sh`.
3. Pull the new images and restart:

    ```bash
    docker compose pull && docker compose up -d
    ```

Database changes run by themselves before the API starts. If you pinned a version with `LOUPEBOX_VERSION`,
change it first.

## Roll back

Set `LOUPEBOX_VERSION` in `.env` to the previous version, run `docker compose pull`, then restore the backup you
made before the upgrade. You need that backup because a newer version may have changed the database in a way
the older one cannot read.

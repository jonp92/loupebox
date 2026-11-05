#!/bin/sh
# Restores a backup made by backup.sh. Replaces the whole database; puts back .env only if there is none.
# Usage, from the folder that holds docker-compose.yml: ./scripts/restore.sh [-y] FILE (checkout) or sh restore.sh [-y] FILE (release).
# -y skips the confirmation. Afterwards the stack starts and migrations bring the database up to the
# version you run; to roll back, set LOUPEBOX_VERSION in .env first.
set -eu

yes=
[ "${1:-}" = -y ] && { yes=1; shift; }
file=${1:?usage: restore.sh [-y] FILE}
[ -f "$file" ] || { echo "No such file: $file" >&2; exit 1; }
[ -f docker-compose.yml ] || { echo "Run this from the folder that holds docker-compose.yml." >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar -xf "$file" -C "$tmp" db.dump env

envdiff=
if [ -f .env ] && ! cmp -s "$tmp/env" .env; then
  envdiff=1
  echo "Your .env differs from the one in the backup. It will be left alone and the backup's copy saved"
  echo "as .env.from-backup. If the encryption keys differ, restored 2FA and webhook secrets cannot be read."
fi

if [ -z "$yes" ]; then
  printf 'This replaces everything in the Loupebox database with %s. Type "yes" to go on: ' "$file"
  read -r answer || true
  [ "$answer" = yes ] || { echo "Stopped; nothing was changed." >&2; exit 1; }
fi

umask 077
if [ ! -f .env ]; then
  cp "$tmp/env" .env && echo "Restored .env from the backup."
elif [ -n "$envdiff" ]; then
  cp "$tmp/env" .env.from-backup
fi

docker compose stop api worker web
docker compose up -d --wait db
# A fresh database rather than pg_restore --clean, so tables from a newer version cannot linger.
docker compose exec -T db dropdb -U ganymede --if-exists --force ganymede
docker compose exec -T db createdb -U ganymede ganymede
docker compose exec -T db pg_restore -U ganymede -d ganymede --exit-on-error < "$tmp/db.dump"
docker compose up -d
echo "Restored $file."

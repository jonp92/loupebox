#!/bin/sh
# Backs up the database and .env into one dated file, and keeps only the newest few.
# Usage, from the folder that holds docker-compose.yml: ./scripts/backup.sh [folder] (checkout) or sh backup.sh [folder] (release).
# The folder defaults to ./backups. BACKUP_KEEP (default 14) sets how many backups to keep; 0 keeps them all.
# Restore with restore.sh.
set -eu

dir=${1:-backups}
keep=${BACKUP_KEEP:-14}
[ -f .env ] || { echo "No .env here; run this from the folder that holds docker-compose.yml." >&2; exit 1; }

umask 077  # the backup holds the encryption keys
mkdir -p "$dir"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Custom format is compressed, and pg_restore can load it into a fresh database.
docker compose exec -T db pg_dump -U ganymede -Fc ganymede > "$tmp/db.dump"
cp .env "$tmp/env"

# Written under a temporary name first, so a failed run never looks like a good backup.
out="$dir/loupebox-$(date -u +%Y-%m-%dT%H%M%SZ).tar"
tar -cf "$out.part" -C "$tmp" db.dump env
mv "$out.part" "$out"
echo "Wrote $out"

# The glob sorts by name, which is by date, so the oldest come first.
if [ "$keep" -gt 0 ]; then
  set -- "$dir"/loupebox-*.tar
  while [ $# -gt "$keep" ]; do
    rm -- "$1" && echo "Removed $1"
    shift
  done
fi

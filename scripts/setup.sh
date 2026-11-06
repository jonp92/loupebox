#!/bin/sh
# First-run setup: writes .env from .env.example with freshly generated secrets.
# Usage, from the folder that holds docker-compose.yml: ./scripts/setup.sh [template] (checkout) or sh setup.sh (release).
# The template defaults to .env.example (env.example in a release download); use deploy/production.env.example on a server.
# Refuses to overwrite an existing .env.
set -eu

# Releases ship the template as env.example (GitHub drops leading dots from asset names).
template=${1:-$([ -f .env.example ] && echo .env.example || echo env.example)}
[ -f "$template" ] || { echo "No such template: $template" >&2; exit 1; }
[ -e .env ] && { echo ".env already exists; delete it first to start over." >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required to generate secrets." >&2; exit 1; }

secret() { openssl rand -base64 48 | tr -d '\n=' | tr '+/' '-_'; }  # URL-safe
dbpass=$(openssl rand -hex 24)

awk -v jwt="$(secret)" -v totp="$(secret)" -v hook="$(secret)" -v sets="$(secret)" -v db="$dbpass" '
  /^JWT_SECRET=$/             { print "JWT_SECRET=" jwt; next }
  /^TOTP_ENCRYPTION_KEY=$/    { print "TOTP_ENCRYPTION_KEY=" totp; next }
  /^WEBHOOK_ENCRYPTION_KEY=$/ { print "WEBHOOK_ENCRYPTION_KEY=" hook; next }
  /^SETTINGS_ENCRYPTION_KEY=$/ { print "SETTINGS_ENCRYPTION_KEY=" sets; next }
  /^POSTGRES_PASSWORD=$/      { print "POSTGRES_PASSWORD=" db; next }
  { gsub(/CHANGE_ME/, db); print }
' "$template" > .env
chmod 600 .env

cat <<MSG
Wrote .env with generated secrets (keep it safe; changing the encryption keys later locks out 2FA, webhooks and saved email credentials).

Next:
  docker compose up -d --build
  docker compose run --rm api python -m scripts.create_superadmin you@example.com
  open http://localhost:8080
MSG

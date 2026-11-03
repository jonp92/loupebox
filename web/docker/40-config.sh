#!/bin/sh
# Runs before nginx starts. Writes the runtime config the SPA reads from /config.js, and the
# Content-Security-Policy, which has to allow the API origin the browser talks to.
# API_URL is operator-supplied (container env), not user input, but it ends up in JS and in a
# header, so refuse anything that is not a bare http(s) origin.
set -eu
API_URL="${API_URL:-http://localhost:8000}"
if ! printf '%s' "$API_URL" | grep -Eq '^https?://[A-Za-z0-9._:-]+/?$'; then
  echo "API_URL must be a bare http(s) origin such as https://feedback.example.com (got: $API_URL)" >&2
  exit 1
fi
API_ORIGIN="${API_URL%/}"
printf 'window.__CONFIG__ = {"API_URL": "%s"};\n' "$API_ORIGIN" > /tmp/config.js
# No inline scripts or styles, no third-party hosts; images (avatars) and fetches go to the API origin only.
printf 'add_header Content-Security-Policy "default-src '"'none'"'; script-src '"'self'"'; style-src '"'self'"'; img-src '"'self'"' %s; connect-src '"'self'"' %s; manifest-src '"'self'"'; worker-src '"'self'"'; base-uri '"'self'"'; form-action '"'self'"'; frame-ancestors '"'none'"'; object-src '"'none'"'" always;\n' "$API_ORIGIN" "$API_ORIGIN" > /tmp/csp.conf

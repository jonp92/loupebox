#!/bin/sh
# Runs before nginx starts. Writes the runtime config the SPA reads from /config.js.
# API_URL is operator-supplied (container env), not user input.
set -eu
printf 'window.__CONFIG__ = {"API_URL": "%s"};\n' "${API_URL:-http://localhost:8000}" > /tmp/config.js

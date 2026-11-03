# Security policy

Loupebox is alpha software. It collects input from the public internet, so we take security reports seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub:
**Security tab → Report a vulnerability** on this repository. Include what you found, how to reproduce it
and the version or commit you tested.

You can expect an acknowledgement within a few days. We will keep you updated, fix confirmed issues as quickly as
we can and credit you in the release notes if you wish.

## Supported versions

Only the latest release receives security fixes while the project is in alpha.

## Scope notes

* The public ingest endpoint is open by design; abuse controls (rate limits, quotas, honeypot, challenge) are
  defense in depth. Bypasses of those controls are in scope.
* Operator secrets (`JWT_SECRET`, provider keys, encryption keys) belong in the environment, never the database.
  A path that exposes one is in scope.

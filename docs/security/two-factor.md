# Two-factor sign-in

Users can set up a code from an authenticator app (any app that supports TOTP, RFC 6238) under
**Profile and password**. It is optional and per person. Nothing changes for people who do not turn it on.

![Two-factor setup](../images/two-factor-dark.png#only-dark)
![Two-factor setup](../images/two-factor-light.png#only-light)

## Turn it on

1. Open your profile and start the setup. You see a QR code and the same key as text.
2. Scan it with your app, then enter the current code and your password to confirm. It only takes effect
   after this.
3. Save the 10 recovery codes. They are shown once, and each works once. Only their hashes are stored.

Signing in then takes two steps: your password, then a code. A code can only be used once. Attempts are
rate limited (`LOGIN_ACCOUNT_LIMIT` per minute and `MFA_HOURLY_LIMIT` per hour).

Turning it on, turning it off and making new recovery codes all need your password, so someone who gets
hold of a signed-in session can't lock you out. Turning it off or making new codes also needs a current code. Turning it on or off
signs out your other sessions.

## Keep the encryption key

Secrets are encrypted in the database with `TOTP_ENCRYPTION_KEY`. Production refuses to start without it.
Elsewhere an empty key means `JWT_SECRET` is used, and changing that later would lock everyone out. Set
`TOTP_ENCRYPTION_KEY` once and keep it. `setup.sh` does this for you.

## If someone is locked out

If they have lost both the app and the recovery codes, a superadmin can choose **Reset 2FA** on the Users
page, or run this on the server:

```bash
docker compose run --rm api python -m scripts.reset_totp user@example.com
```

Either way the person is signed out everywhere. There is no other way back in without a code.

## Requiring 2FA for everyone

A superadmin with 2FA on can turn on **Require two-factor authentication** under System, Accounts & limits
(or set `REQUIRE_TOTP=true`). It applies at once to every account, with no grace period. Someone without
2FA can still sign in or reset their password, but then sees only the Profile page until they set 2FA up, and
nobody can turn it off while the setting is on. Resetting a user's 2FA sends them back to that setup.

If the setting itself has to come off, for example because no superadmin can get a code, run:

```bash
docker compose run --rm api python -m scripts.reset_totp --stop-requiring
```

That removes the setting saved on the System page. If `REQUIRE_TOTP=true` is in your `.env`, remove it too.

## For developers

* `POST /v1/api/auth/login` answers `{"mfa_required": true, "mfa_token": "..."}` instead of tokens.
* `POST /v1/api/auth/login/totp` with that token (valid for 5 minutes, and not usable as an access token)
  and a code opens the session.
* `DELETE /v1/api/users/{id}/totp` is what Reset 2FA calls.

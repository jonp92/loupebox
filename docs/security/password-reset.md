# Password reset

The sign-in page shows **Forgot password?** when the server can send email. That needs two things:
`PUBLIC_URL` is set (it builds the link) and an [email provider](../notifications/index.md) is set up. If
either is missing the link is hidden, and a superadmin resets passwords on the Users page instead.

## How it works

* The email links to `{PUBLIC_URL}/reset-password#token=...`. The token is in the part of the address after
  `#`, which browsers do not send to servers, so it stays out of logs. The page removes it from the address bar.
* A link works once and expires after `PASSWORD_RESET_MINUTES` (default 30). A newer request replaces older
  links. Only a hash of the token is stored.
* The response is always the same, and the email is sent after replying, so nobody can use the form to find out
  whether an address has an account.
* Limits are 3 requests per address (`PASSWORD_RESET_EMAIL_LIMIT`) and 10 per visitor address
  (`PASSWORD_RESET_IP_LIMIT`), each per hour. They also stop strangers from using up your email provider's
  daily allowance.
* Using a link changes the password, signs the person out everywhere and emails them that it happened. It does
  not sign them in, and it does **not** turn off two-factor. They still need their code.
* The email is sent straight away, not through the queue, so there are no retries. If sending fails it is
  logged, and the person has to ask again.

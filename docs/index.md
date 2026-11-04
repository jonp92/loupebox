# Loupebox

Loupebox is a feedback inbox you run yourself. Visitors to your website or tool send a message from a
form or a small widget. You and your team read it, sort it, answer it and get an email when something new
arrives.

![The feedback list in Loupebox](images/feedback-list-dark.png#only-dark)
![The feedback list in Loupebox](images/feedback-list-light.png#only-light)

It is a good fit when you have a few small sites or tools and want one place for what people tell you. It is
not a help desk: there are no tickets, queues or response-time targets.

!!! warning "Alpha software"
    Loupebox is at version 0.1 alpha. Things may change between releases, so read the
    [changelog](https://github.com/jonp92/loupebox/blob/master/CHANGELOG.md) before you upgrade and
    [back up your database](install/backups-upgrades.md) first. See [Known limits](reference/limitations.md).

## What you get

* A feedback form or widget you add to any site with two lines of code.
* An inbox with filters, statuses, assignees, tags and private notes.
* Replies sent by email to the person who wrote in.
* Email and webhook alerts for new feedback.
* Several sites in one install, with a role for each person on each site (viewer, editor, admin).
* Spam protection that works without a CAPTCHA, and an optional proof-of-work challenge.
* An admin app that works on phones and can be installed like an app.

## Where to start

1. [Install with Docker](install/docker.md). It takes about five minutes.
2. Follow [First steps](install/first-steps.md) to create a site and send a test message.
3. Add the [widget](collect/widget.md) to your website.
4. Set up [email alerts](notifications/index.md) so you hear about new feedback.
5. When you are ready to go live, read [Put it on the internet](install/reverse-proxy.md).

## Help and source code

The code, issues and discussions are on [GitHub](https://github.com/jonp92/loupebox). Report bugs and
ask questions in [issues](https://github.com/jonp92/loupebox/issues). Report a security problem privately
through the repository's [security page](https://github.com/jonp92/loupebox/security).

The server is licensed under the AGPL-3.0. The widget is licensed under Apache-2.0, so you can use it on
any site.

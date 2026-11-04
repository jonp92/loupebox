# Loupebox

Loupebox is a web form inbox you run yourself. Visitors to your website or tool send a message and other
information from a form or a small widget. You and anyone you choose can read, sort and reply to it from a web
app. Set up a notification channel to hear about new submissions by email or webhook. Other channel types can be
added as plugins.

![The feedback list in Loupebox](images/feedback-list-dark.png#only-dark)
![The feedback list in Loupebox](images/feedback-list-light.png#only-light)

Loupebox is meant for self-hosting, for when you have a static page or an app and want to collect feedback from
its users. It is not a full ticketing system or a CRM. Its public-safe site keys let any static website have a
form without needing its own application server.

!!! warning "Alpha software"
    Loupebox is at version 0.1 alpha. Things may change between releases, so read the
    [changelog](https://github.com/jonp92/loupebox/blob/master/CHANGELOG.md) before you upgrade and
    [back up your database](install/backups-upgrades.md) first. See [Known limits](reference/limitations.md).

## What you get

* A feedback form or widget you add to any site with two lines of code, no application server necessary.
* An inbox with filters, statuses, assignees, tags and private notes.
* Replies sent by email to the person who wrote in.
* Email and webhook alerts for new feedback.
* Several sites in one install, with a role for each person on each site (viewer, editor, admin).
* Spam protection that works without a CAPTCHA, and an optional proof-of-work challenge.
* An admin app that works on phones and can be installed as a PWA.

## Where to start

1. [Install with Docker](install/docker.md). Get started in about five minutes.
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

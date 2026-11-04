# First steps

After [installing](docker.md), sign in with the administrator account you created.

![The sign-in page](../images/login-dark.png#only-dark)
![The sign-in page](../images/login-light.png#only-light)

## Create a site

A site is one website or tool that sends you feedback. Each site has its own inbox, team and settings.

1. Choose **Sites** in the top bar, then **New site**.
2. Give it a name.
3. Under allowed origins, list every address the form will run on, for example
   `https://www.example.com`. Include `http://localhost:3000` (or whatever port you use) while you test.
   An origin is the scheme, host and port, with no path and no wildcards.

![The sites list](../images/sites-dark.png#only-dark)
![The sites list](../images/sites-light.png#only-light)

## Find the key and the snippet

Open the site and choose **Settings**. You will see the site's public key, which starts with `pk_`. It is
safe to put in a web page. Below it is the widget snippet with your key already filled in.

![Site settings with the widget snippet](../images/settings-dark.png#only-dark)
![Site settings with the widget snippet](../images/settings-light.png#only-light)

## Send a test message

Copy the snippet into a page that is served from one of your allowed origins. Open the page, click the
feedback button and send a message. It appears in the site's **Feedback** tab within a moment.

If it does not, see [Debugging](../collect/own-form.md#debugging). The usual cause is an origin that is not on
the allowed list.

## Add your team

Open the site's **Members** tab to add people by email and give each a role: viewer, editor or admin. See
[People and roles](../manage/roles.md). Create the user accounts first under **Users** in the top bar.

## Get alerts

Open the site's **Notifications** tab to be emailed about new feedback. You need to set up an email service
first. See [Email alerts](../notifications/index.md).

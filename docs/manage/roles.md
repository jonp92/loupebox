# People and roles

## Users

A **superadmin** manages the whole install. They create sites and users, and have admin rights on every
site. Everyone else gets access to a site through a role on that site. A person can have different roles on
different sites.

Superadmins manage accounts on the **Users** page and server settings on the **System** page (see
[Settings](../reference/configuration.md#changing-settings-in-the-app)). Only they can change names and email addresses. People
change their own password and picture under **Profile and password**. Uploads are cropped to 256 by 256
pixels, and the file is limited to 64 KB.

## Site roles

| Role | Can |
|---|---|
| Viewer | Read feedback, tags, assignees, notes and replies. |
| Editor | Everything a viewer can, plus change status, assign, tag, add notes and send replies. |
| Admin | Everything an editor can, plus delete feedback and manage the site's settings, key, members and notifications. |

People who are not members of a site cannot see it. The server answers as if the site does not exist, so
nobody can find site ids by guessing.

![A site's members](../images/members-dark.png#only-dark)
![A site's members](../images/members-light.png#only-light)

Add members from a site's **Members** tab. The person needs a user account first.

## If someone is locked out

A superadmin can reset a password on the Users page, or people can reset it themselves by email once [email is set up](../security/password-reset.md). For two-factor problems, see
[Two-factor sign-in](../security/two-factor.md#if-someone-is-locked-out).

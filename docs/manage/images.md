# Images with feedback

Visitors can attach screenshots to their feedback. It is **off by default** and each site turns it on for
itself.

## Turn it on

Open **Site → Settings** and tick **Accept images with feedback**. The hint under it shows the limits of your
server. The [feedback widget](../collect/widget.md#images) then shows an **Add image** button, and accepts images
pasted or dropped anywhere on its form. You do not need to change the snippet on your website.

If you build your own form, see [Sending images](../collect/api.md#sending-images).

## What visitors can send

By default up to 3 images per submission, PNG, JPEG or WebP, up to 5 MB each. The limits are server settings
(`ATTACHMENT_MAX_COUNT`, `ATTACHMENT_MAX_BYTES`, `ATTACHMENT_MAX_EDGE`, see
[Configuration](../reference/configuration.md#images)).

Every image is decoded and written out again before it is stored:

* Only real PNG, JPEG and WebP pictures get through. SVG, GIF, PDF and anything disguised as an image are refused.
* Pictures larger than 2048 pixels on the longer side are scaled down. Pictures of more than 20 million pixels
  are refused without being decoded.
* Camera and location data (EXIF), embedded text and anything hidden after the pixels are dropped. Rotation is
  applied first.
* An animated image keeps its first frame.

If any image in a submission is refused, the whole submission is refused with a message about that image, so the
visitor can fix it and send again.

Images from submissions that land in **Spam**, are caught by the honeypot or are duplicates are not stored.

## Seeing them

Open the feedback item. The images are under the message as thumbnails; select one to see it full size, move
between them with **Previous** and **Next** (or the arrow keys) and close it with `Escape`. The feedback list
shows a paperclip and the number of images on items that have any.

Images are served only to signed-in members of the site, with the same roles as the feedback itself. There is no
public link to an image, so a copied address shows nothing to anyone else.

## Deleting them

* **Delete image** in the viewer removes one image and keeps the message. Site admins only, and recorded in the
  [audit log](../security/audit-log.md).
* Deleting a feedback item, [bulk deleting](triage.md#bulk-actions), a site's
  [retention rules](retention.md), [erasing a person's data](retention.md#export-or-erase-personal-data) and
  deleting the site all delete the image files too.
* The worker checks once a day for files that no feedback refers to (for example after a crash) and removes them.

## Where the files are

In the folder `ATTACHMENTS_DIR`. The Docker setup keeps it in a volume that the API and the worker share, and
[backups](../install/backups-upgrades.md) include it. With a bare install, make sure the API and the worker use
the same folder and back it up with the database.

The local folder is one of the storage backends (`STORAGE_BACKEND=local`). It needs one disk that every API
container and the worker can reach, so running more than one API container on separate machines needs a shared
volume. Other backends, such as S3, can be added without changing the rest.

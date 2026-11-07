# Image storage

[Images sent with feedback](../manage/images.md) are files, and they can live in two places:

* **This server's disk** (the default). Nothing to set up. The Docker setup keeps them in a volume that the API
  and the worker share.
* **An S3 bucket.** Amazon S3 or any service that speaks the S3 protocol: Cloudflare R2, Backblaze B2, DigitalOcean
  Spaces, Wasabi, MinIO, Ceph and others. Use it when the server's disk is small or short-lived, when you run
  more than one API container on separate machines, or when you want the provider to keep the files safe.

You choose in the admin app, with no restart: **System → Image storage**. Only superadmins can see it.

## Set up a bucket

1. Create a **private** bucket. Do not make it public: Loupebox serves images itself, only to signed-in members of
   the site, and never links to the bucket.
2. Create an access key that can list the bucket and read, write and delete objects in it. For Amazon S3, a policy
   like this (replace the bucket name):

    ```json
    {
      "Version": "2012-10-17",
      "Statement": [
        { "Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::my-loupebox-images" },
        { "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
          "Resource": "arn:aws:s3:::my-loupebox-images/*" }
      ]
    }
    ```

3. In **System → Image storage**, choose *S3 bucket (or compatible)* and fill in:

| Setting | What to enter |
|---|---|
| Endpoint address | Empty for Amazon S3. For any other provider, its S3 address (table below). |
| Region | Your bucket's region. Empty means `us-east-1`. Cloudflare R2 uses `auto`. |
| Bucket | The bucket name. |
| Access key ID, Secret access key | The key you created. The secret is stored encrypted and cannot be read back. |
| Path-style addressing | Turn on for MinIO and most self-hosted servers (`https://host/bucket/file`). |
| Folder in the bucket | Optional. Lets the bucket hold other things too. |

4. **Save**, then choose **Test connection**. It writes a small file, reads it back and deletes it, and says what is
   wrong if it cannot: a wrong key, a missing bucket, an address that cannot be reached.

The settings can also come from `.env` (`STORAGE_BACKEND=s3`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`,
`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PATH_STYLE`, `S3_PREFIX`). Values saved in the admin app win.

## Provider values

| Provider | Endpoint address | Region | Path-style |
|---|---|---|---|
| Amazon S3 | empty | for example `eu-west-1` | off |
| Cloudflare R2 | `https://ACCOUNT_ID.r2.cloudflarestorage.com` | `auto` | off |
| Backblaze B2 | `https://s3.REGION.backblazeb2.com` | for example `us-west-004` | off |
| DigitalOcean Spaces | `https://REGION.digitaloceanspaces.com` | for example `nyc3` | off |
| Wasabi | `https://s3.REGION.wasabisys.com` | for example `us-east-1` | off |
| MinIO and other self-hosted | `http://HOST:9000` (your address) | `us-east-1` | **on** |

These come from each provider's documentation. Loupebox's own tests run against a real S3-protocol server, and
it has been run against Scality CloudServer and SeaweedFS. If a provider behaves differently, **Test connection**
shows the provider's error code. Older servers that cannot delete many files in one request are handled: Loupebox
falls back to deleting them one by one.

The endpoint is called from the server, so it can be a private address. That is on purpose, for self-hosted storage,
and it is why only superadmins can change it.

## Switching, and moving what is already stored

Changing the storage only affects **new** images. Each image remembers where its file is, so images stored before
the switch keep working, and deleting feedback removes the file from wherever it is.

To bring everything into one place, open **System → Image storage**. It says how many images are still elsewhere
and has a **Move images** button. It copies each file to the current storage, switches the image over and removes
the old copy, a few at a time, so keep the page open until it says it is done. It is safe to stop and start again,
and safe while people submit and delete feedback. A file that is already missing is counted and skipped, and a
file that cannot be copied is reported with the reason and left where it is.

You can also switch back: select *This server's disk* and move again.

## Things to know

* **Backups.** `backup.sh` saves the images on the server's disk. Images in a bucket are **not** in it: keep them safe
  with the provider (versioning, replication). Restoring a database backup does not change a bucket.
* **Deleting means deleting.** Retention, erasing a person's data and deleting feedback delete the objects. If you turn
  on bucket **versioning** or replication, old versions can stay behind. Add a lifecycle rule that expires old
  versions, so the promise you make to visitors holds. Do not turn on object lock on this bucket.
* **Stray files.** The worker checks daily for files that no feedback refers to, in every storage that holds images, and
  removes them. It only touches names Loupebox wrote, so a shared bucket with other data is safe.
* **More than one API container** is fine with a bucket: nothing needs to be shared on disk.
* The worker needs the same settings as the API. Settings saved in the admin app reach it within a pass or two;
  settings in `.env` must be in the worker's environment too (the compose file passes them to both).

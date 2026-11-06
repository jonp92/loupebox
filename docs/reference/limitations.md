# Known limits

Loupebox is alpha software. These are the limits to know about today.

* **More than one API container needs Redis.** Rate limits live in the API's memory unless `REDIS_URL` is
  set. See [More than one API container](../install/production.md#more-than-one-api-container).
* **Images need one shared disk.** The only storage backend today is a local folder, so every API container
  and the worker must see the same folder. The personal-data export lists a person's images but does not
  contain the files. See [Images with feedback](../manage/images.md).
* **Replies are one way.** Loupebox sends replies by email but does not read the answers. Replies from the
  person go to the editor's own inbox.
* **It has not been load tested.** It is meant for small sites and tools. Benchmarks are planned.
* **Not a help desk.** There are no tickets, queues or response-time targets, and none are planned.
* **Breaking changes can happen** between 0.x releases. Read the
  [changelog](https://github.com/jonp92/loupebox/blob/master/CHANGELOG.md) and
  [back up](../install/backups-upgrades.md) before you upgrade.

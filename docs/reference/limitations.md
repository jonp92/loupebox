# Known limits

Loupebox is alpha software. These are the limits to know about today.

* **Run one API container.** Rate limits live in the API's memory. With more than one copy, each copy counts
  separately and visitors get a multiple of the limit. Moving the limits to Redis is planned.
* **Replies are one way.** Loupebox sends replies by email but does not read the answers. Replies from the
  person go to the editor's own inbox.
* **It has not been load tested.** It is meant for small sites and tools. Benchmarks are planned.
* **Not a help desk.** There are no tickets, queues or response-time targets, and none are planned.
* **Breaking changes can happen** between 0.x releases. Read the
  [changelog](https://github.com/jonp92/loupebox/blob/master/CHANGELOG.md) and
  [back up](../install/backups-upgrades.md) before you upgrade.

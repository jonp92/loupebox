# Assign, tag and note

## Assignee

Give an item to one person so everyone knows who is dealing with it. The assignee must be an editor or
admin of the site. If someone loses editor access, their assignments are cleared.

* Tap or click the assignee on a card to pick someone. You can also right-click it, long-press it on a
  phone, or use the **...** button. Or tick several items and choose **Assign to...**.
* The list has **Assigned to me** and **Unassigned** tabs with counts, and a filter for each person.
* Your dashboard lists your open items from every site.
* The picker searches by name, so it works on sites with many members. It offers **Me** and the people you
  picked recently.

![Picking an assignee](../images/assignee-dark.png#only-dark)
![Picking an assignee](../images/assignee-light.png#only-light)

## Tags

Tags are free text you make up per site, such as `needs-review`. They are saved in lower case with dashes,
and an item can have up to 10. Filter the list by tag, and see all tags with counts.

## Notes

Notes are private. The person who sent the feedback never sees them, and they are not in exports. Everyone
on the site can read notes, editors can add them, and people can delete their own. Admins can delete any.

The list shows how many notes each item has. The notes themselves are on the item's page.

## In the API

* `PATCH /v1/api/sites/{id}/feedback/{feedback_id}` takes any of `status`, `assignee_id` and `tags`.
* The list filters with `?assignee=<user id>` or `?assignee=none`, and `?tag=`.
* `GET .../feedback/tags` lists tags with counts. `GET .../feedback/assignees?q=` finds people (at most 20).
* The bulk call also takes `assign`, `add_tag` and `remove_tag`. See [Triage](triage.md#bulk-actions).

# Custom fields

Ask visitors more than their message: which plan they are on, whether they are in your beta, which company they
are from. A site can have up to **10** custom fields. They appear in the [feedback widget](../collect/widget.md#fields-from-the-site-settings)
by themselves, and their answers are shown, filtered on and exported alongside the feedback.

## Add a field

Open **Site → Settings → Custom fields** and choose **Add field**.

| Type | What the visitor sees | Stored as |
|---|---|---|
| Choose one | A drop-down of your options | The option's stored value |
| Yes or no | A checkbox | `true` or `false` |
| Short text | A one-line box (up to 256 characters) | The text |

* **Required** makes the visitor answer before the form sends. For a checkbox it means the box must be ticked.
* **Show the answer on feedback rows** adds a small badge to each row in the list (at most 2 fields). A checkbox
  only shows when it is ticked.
* The **id** is the key the answer is stored under (`plan`, `beta_tester`). It and the type are fixed once the
  field exists, so renaming never orphans answers. `issue_type`, `widget_version` and `locale` are reserved.
* An option's stored value is taken from its label when you first save it and never changes after. Renaming an
  option changes what visitors read, not what is stored, so filters and exports stay consistent.

Use the arrows to reorder; the widget follows the same order.

## Translate a field

Under **Translations**, add a language code such as `de` or `pt-BR` (up to 8 languages per site) and fill in the
question and each option in that language. The widget shows the one that matches the visitor's page language
(`<html lang>`, or the widget's `locale` option); anything left blank falls back to your own text. Translations
never change what is stored.

## What happens to the answers

* The feedback page shows them first, with your labels. Anything else the page sent is under **Other data**.
* On the list, **Custom fields** filters on them; see [Triage](triage.md#filters).
* [Export](export.md) gets one column per field.
* An answer that no longer fits (for example an option you have since deleted, from a form that was still open)
  is dropped, and the feedback is kept. A missing required answer is refused with a message naming the field.

## Changing and deleting fields

Deleting a field stops visitors being asked; answers already collected stay with each feedback, under **Other
data**. Deleted options can still be filtered on by their stored value.

## API

Fields are the `custom_fields` list of `PATCH /v1/api/sites/{id}` (admin only) and are read back from
`GET /v1/api/sites/{id}`. The list is replaced as a whole. The form-facing copy is in `GET /v1/api/feedback/config`.

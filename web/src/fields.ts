import type { CustomField } from "./api";

/** An answer as text: a choice's label (its stored value if the site has since removed the option), yes or no,
 * or the text itself. */
export function answerText(field: CustomField, value: unknown): string {
  if (field.type === "checkbox") return value === true ? "Yes" : "No";
  const text = String(value ?? "");
  return field.type === "select" ? (field.options.find((o) => o.value === text)?.label ?? text) : text;
}

/** Whether feedback answered `field` at all (an unticked checkbox is an answer, a missing key is not). */
export const answered = (metadata: Record<string, unknown>, field: CustomField) => {
  const v = metadata[field.id];
  return v !== undefined && v !== null && v !== "";
};

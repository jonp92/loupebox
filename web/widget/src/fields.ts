import type { ExtraField } from "./options";

/** A field as the form draws it, whether the page or the site defined it. */
export interface FieldSpec {
  id: string;
  label: string;
  type: "text" | "textarea" | "select" | "checkbox";
  required: boolean;
  /** For `select`: `value` is what is sent, `label` what the visitor reads. */
  options: { value: string; label: string }[];
  maxLength?: number;
}

/** A custom field defined in the site's settings, as `GET /feedback/config` lists it. */
export interface SiteField {
  id: string;
  type: "text" | "select" | "checkbox";
  label: string;
  required: boolean;
  options: { value: string; label: string }[];
  maxLength: number | null;
  translations: Record<string, { label?: string; options?: Record<string, string> }>;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

/** The fields out of a config response. Anything malformed is skipped, so a server newer or older than the
 * widget degrades to fewer fields rather than a broken form. */
export function parseSiteFields(raw: unknown): SiteField[] {
  if (!Array.isArray(raw)) return [];
  const out: SiteField[] = [];
  for (const f of raw) {
    if (!isObject(f)) continue;
    const id = text(f.id);
    const label = text(f.label);
    if (!id || !label || !/^[a-z0-9_-]{1,32}$/.test(id)) continue;
    if (f.type !== "text" && f.type !== "select" && f.type !== "checkbox") continue; // a type this widget lacks
    const options = (Array.isArray(f.options) ? f.options : []).flatMap((o) => {
      const value = isObject(o) ? text(o.value) : null;
      const name = isObject(o) ? text(o.label) : null;
      return value && name ? [{ value, label: name }] : [];
    });
    if (f.type === "select" && !options.length) continue;
    const translations: SiteField["translations"] = {};
    for (const [code, t] of Object.entries(isObject(f.translations) ? f.translations : {})) {
      if (!isObject(t)) continue;
      const answers = Object.fromEntries(
        Object.entries(isObject(t.options) ? t.options : {}).filter(([, v]) => typeof v === "string" && v.trim()),
      ) as Record<string, string>;
      translations[code] = { ...(text(t.label) && { label: text(t.label)! }), options: answers };
    }
    out.push({
      id, type: f.type, label, required: f.required === true, options,
      maxLength: typeof f.max_length === "number" && f.max_length > 0 ? f.max_length : null,
      translations,
    });
  }
  return out;
}

/** The entry of `available` that best matches the visitor's language, or null. `pt-BR` matches `pt-BR`, then
 * `pt`, then any other `pt-*`; case does not matter. */
export function pickLocale(wanted: string, available: string[]): string | null {
  const byLower = new Map(available.map((a) => [a.toLowerCase(), a]));
  let tag = wanted.trim().replace(/_/g, "-").toLowerCase();
  const base = tag.split("-")[0];
  while (tag) {
    const hit = byLower.get(tag);
    if (hit) return hit;
    const cut = tag.lastIndexOf("-");
    if (cut < 0) break;
    tag = tag.slice(0, cut);
  }
  return base ? (available.find((a) => a.toLowerCase().split("-")[0] === base) ?? null) : null;
}

/** The form's version of a site field in the visitor's language. Missing translations use the site's own text. */
export function localize(field: SiteField, locale: string): FieldSpec {
  const code = pickLocale(locale, Object.keys(field.translations));
  const tr = code ? field.translations[code] : undefined;
  return {
    id: field.id,
    type: field.type,
    required: field.required,
    label: tr?.label ?? field.label,
    options: field.options.map((o) => ({ value: o.value, label: tr?.options?.[o.value] ?? o.label })),
    ...(field.maxLength ? { maxLength: field.maxLength } : {}),
  };
}

export function fromExtra(f: ExtraField): FieldSpec {
  return {
    id: f.id,
    label: f.label,
    type: f.type ?? "text",
    required: Boolean(f.required),
    options: (f.options ?? []).map((o) => ({ value: o, label: o })),
    ...(f.maxLength ? { maxLength: f.maxLength } : {}),
  };
}

/** The `<html lang>` of the page, else the browser's language: what a translated field should match. */
export function detectLocale(): string {
  const page = typeof document === "undefined" ? "" : document.documentElement.lang;
  return page || (typeof navigator === "undefined" ? "" : navigator.language) || "";
}

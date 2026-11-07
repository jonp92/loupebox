import { defaultStrings, type Strings } from "./i18n";
import { VERSION } from "./version";

/** A badge the visitor picks. Sent as `metadata.issue_type` (the `id`). */
export interface IssueType {
  /** Stable machine value: lowercase letters, digits, `-` and `_`, up to 32 characters. */
  id: string;
  /** What the visitor sees (up to 40 characters). Rendered as text, never as HTML. */
  label: string;
  /** A short text icon such as an emoji. The built-in types use drawn icons instead. */
  icon?: string;
  /** Accent color of the badge when selected (any CSS color). */
  color?: string;
}

export type FieldMode = false | "optional" | "required";
export type MetadataValue = string | number | boolean | null;

/** A custom field. Its value is sent in `metadata` under `id`. */
export interface ExtraField {
  id: string;
  label: string;
  type?: "text" | "textarea" | "select" | "checkbox";
  required?: boolean;
  /** For `select`: the choices (also the values that are sent). */
  options?: string[];
  maxLength?: number;
}

export type ColorName = "accent" | "accentText" | "background" | "text" | "muted" | "border";

export interface WidgetOptions {
  /** Base URL of the API including the `/v1/api` prefix, no trailing slash. */
  url: string;
  /** The site's public key (`pk_...`). */
  key: string;
  /** `floating` (button plus panel, default) or `inline` (the form rendered inside `target`). */
  mode?: "floating" | "inline";
  /** Where to render in `inline` mode: an element or a CSS selector. */
  target?: string | HTMLElement;
  position?: "bottom-right" | "bottom-left";
  /** Show the launcher button (default true). Set false and call `open()` from your own button. */
  launcher?: boolean;
  /** The badges, or `false` for none. Defaults to bug, idea, question and praise. */
  issueTypes?: IssueType[] | false;
  defaultIssueType?: string;
  requireIssueType?: boolean;
  fields?: { rating?: boolean; name?: FieldMode; email?: FieldMode };
  extraFields?: ExtraField[];
  /** Extra data sent with every submission (an object, or a function called at submit time). */
  metadata?: Record<string, MetadataValue> | (() => Record<string, MetadataValue>);
  /** Page URL to report (default `location.href`). */
  pageUrl?: string | (() => string);
  theme?: "auto" | "light" | "dark";
  colors?: Partial<Record<ColorName, string>>;
  /** Corner radius in px. */
  radius?: number;
  fontFamily?: string;
  zIndex?: number;
  strings?: Partial<Strings>;
  /** Milliseconds before the panel closes after a successful send (default 2500, 0 keeps it open). */
  closeDelay?: number;
  /** Offer image upload when the site accepts images (default true). */
  images?: boolean;
  /** Offer "Capture this page" (screen capture with a redact editor) where the browser can, when images are on (default true). */
  capture?: boolean;
  /** Last look at what will be sent. Return a changed payload, or `false` to cancel. */
  beforeSubmit?: (payload: SubmitPayload) => SubmitPayload | false | Promise<SubmitPayload | false>;
}

/** What `beforeSubmit` sees and may change. */
export interface SubmitPayload {
  message: string;
  rating?: number;
  name?: string;
  email?: string;
  issueType?: string;
  metadata: Record<string, MetadataValue>;
}

export class LoupeboxConfigError extends Error {
  constructor(message: string) {
    super(`[loupebox] ${message}`);
    this.name = "LoupeboxConfigError";
  }
}

export interface ResolvedOptions {
  url: string;
  key: string;
  mode: "floating" | "inline";
  target: string | HTMLElement | undefined;
  position: "bottom-right" | "bottom-left";
  launcher: boolean;
  issueTypes: IssueType[];
  defaultIssueType: string | undefined;
  requireIssueType: boolean;
  fields: { rating: boolean; name: FieldMode; email: FieldMode };
  extraFields: ExtraField[];
  metadata: WidgetOptions["metadata"];
  pageUrl: WidgetOptions["pageUrl"];
  theme: "auto" | "light" | "dark";
  colors: Partial<Record<ColorName, string>>;
  radius: number | undefined;
  fontFamily: string | undefined;
  zIndex: number | undefined;
  strings: Strings;
  closeDelay: number;
  images: boolean;
  capture: boolean;
  beforeSubmit: WidgetOptions["beforeSubmit"];
}

export const defaultIssueTypes: IssueType[] = [
  { id: "bug", label: "Bug", color: "#d64545" },
  { id: "idea", label: "Idea", color: "#b7791f" },
  { id: "question", label: "Question", color: "#2b6cb0" },
  { id: "praise", label: "Praise", color: "#2f855a" },
];

const KNOWN = new Set<string>([
  "url", "key", "mode", "target", "position", "launcher", "issueTypes", "defaultIssueType", "requireIssueType",
  "fields", "extraFields", "metadata", "pageUrl", "theme", "colors", "radius", "fontFamily", "zIndex", "strings",
  "closeDelay", "images", "capture", "beforeSubmit",
]);
const ID = /^[a-z0-9_-]{1,32}$/;
const COLOR_NAMES: ColorName[] = ["accent", "accentText", "background", "text", "muted", "border"];
/** Hex, rgb()/hsl() style functions and plain names: enough for colors, nothing that can carry a url(). */
const SAFE_COLOR = /^(#[0-9a-f]{3,8}|[a-z]{3,20}|(rgb|hsl)a?\([0-9a-z .,%/+-]{1,60}\))$/i;
const SAFE_FONT = /^[\w\s,'"-]{1,200}$/;
export const MAX_METADATA_KEYS = 20;

function warn(message: string): void {
  if (typeof console !== "undefined") console.warn(`[loupebox] ${message}`);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T, name: string): T {
  if (value === undefined) return fallback;
  if (allowed.includes(value as T)) return value as T;
  throw new LoupeboxConfigError(`"${name}" must be one of ${allowed.map((a) => `"${a}"`).join(", ")}`);
}

function fieldMode(value: unknown, fallback: FieldMode, name: string): FieldMode {
  if (value === undefined) return fallback;
  if (value === false || value === "optional" || value === "required") return value;
  throw new LoupeboxConfigError(`"fields.${name}" must be false, "optional" or "required"`);
}

/**
 * Validate and fill in defaults. A wrong value throws a clear error; an option this version doesn't know
 * is ignored with a console warning, so a page configured for a newer widget still works on an older one.
 */
export function normalizeOptions(input: WidgetOptions): ResolvedOptions {
  if (!input || typeof input !== "object") throw new LoupeboxConfigError("createWidget needs an options object");
  for (const name of Object.keys(input)) {
    if (!KNOWN.has(name)) warn(`ignoring unknown option "${name}" (this is widget v${VERSION}; is the page configured for a newer one?)`);
  }

  if (typeof input.key !== "string" || !input.key) throw new LoupeboxConfigError(`"key" is required (the site's public key)`);
  if (typeof input.url !== "string" || !/^https?:\/\//i.test(input.url)) {
    throw new LoupeboxConfigError(`"url" must be the API base URL, e.g. https://feedback.example.com/v1/api`);
  }
  const url = input.url.replace(/\/+$/, "");
  if (!/\/v1\/api$/.test(url)) {
    warn(`"url" should end with /v1/api (got ${url}); requests to ${url}/feedback will 404 otherwise`);
  }

  const mode = oneOf(input.mode, ["floating", "inline"] as const, "floating", "mode");
  if (mode === "inline" && !input.target) throw new LoupeboxConfigError(`"target" is required when mode is "inline"`);

  let issueTypes: IssueType[] = [];
  if (input.issueTypes === undefined) issueTypes = defaultIssueTypes.map((t) => ({ ...t }));
  else if (input.issueTypes !== false) {
    if (!Array.isArray(input.issueTypes)) throw new LoupeboxConfigError(`"issueTypes" must be an array or false`);
    const seen = new Set<string>();
    for (const type of input.issueTypes) {
      if (!type || typeof type.id !== "string" || !ID.test(type.id)) {
        throw new LoupeboxConfigError(`issue type ids must be 1-32 characters of a-z, 0-9, "-" or "_" (got ${JSON.stringify(type?.id)})`);
      }
      if (seen.has(type.id)) throw new LoupeboxConfigError(`duplicate issue type id "${type.id}"`);
      if (typeof type.label !== "string" || !type.label.trim() || type.label.length > 40) {
        throw new LoupeboxConfigError(`issue type "${type.id}" needs a label of 1-40 characters`);
      }
      seen.add(type.id);
      let color = type.color;
      if (color !== undefined && !SAFE_COLOR.test(color)) {
        warn(`ignoring color "${color}" on issue type "${type.id}"`);
        color = undefined;
      }
      issueTypes.push({ id: type.id, label: type.label.trim(), icon: type.icon?.slice(0, 4), color });
    }
  }
  if (input.defaultIssueType !== undefined && !issueTypes.some((t) => t.id === input.defaultIssueType)) {
    throw new LoupeboxConfigError(`"defaultIssueType" ("${input.defaultIssueType}") is not one of the issue types`);
  }

  const extraFields: ExtraField[] = [];
  const reserved = new Set(["issue_type", "widget_version"]);
  for (const field of input.extraFields ?? []) {
    if (!field || typeof field.id !== "string" || !ID.test(field.id)) {
      throw new LoupeboxConfigError(`extra field ids must be 1-32 characters of a-z, 0-9, "-" or "_" (got ${JSON.stringify(field?.id)})`);
    }
    if (reserved.has(field.id)) throw new LoupeboxConfigError(`extra field id "${field.id}" is reserved`);
    reserved.add(field.id);
    if (typeof field.label !== "string" || !field.label.trim()) throw new LoupeboxConfigError(`extra field "${field.id}" needs a label`);
    const type = oneOf(field.type, ["text", "textarea", "select", "checkbox"] as const, "text", `extraFields.${field.id}.type`);
    if (type === "select" && !field.options?.length) throw new LoupeboxConfigError(`select field "${field.id}" needs options`);
    extraFields.push({ ...field, type });
  }

  const colors: Partial<Record<ColorName, string>> = {};
  for (const [name, value] of Object.entries(input.colors ?? {})) {
    if (!COLOR_NAMES.includes(name as ColorName)) warn(`ignoring unknown color "${name}"`);
    else if (typeof value !== "string" || !SAFE_COLOR.test(value)) warn(`ignoring color "${String(value)}" for "${name}"`);
    else colors[name as ColorName] = value;
  }
  let fontFamily = input.fontFamily;
  if (fontFamily !== undefined && !SAFE_FONT.test(fontFamily)) {
    warn(`ignoring fontFamily "${fontFamily}"`);
    fontFamily = undefined;
  }

  const strings: Strings = { ...defaultStrings };
  for (const [name, value] of Object.entries(input.strings ?? {})) {
    if (!(name in defaultStrings)) warn(`ignoring unknown string "${name}"`);
    else if (typeof value === "string") strings[name as keyof Strings] = value;
  }

  const closeDelay = input.closeDelay ?? 2500;
  if (typeof closeDelay !== "number" || closeDelay < 0) throw new LoupeboxConfigError(`"closeDelay" must be a number of milliseconds`);

  return {
    url,
    key: input.key,
    mode,
    target: input.target,
    position: oneOf(input.position, ["bottom-right", "bottom-left"] as const, "bottom-right", "position"),
    launcher: input.launcher ?? true,
    issueTypes,
    defaultIssueType: input.defaultIssueType,
    requireIssueType: input.requireIssueType ?? false,
    fields: {
      rating: input.fields?.rating ?? false,
      name: fieldMode(input.fields?.name, false, "name"),
      email: fieldMode(input.fields?.email, "optional", "email"),
    },
    extraFields,
    metadata: input.metadata,
    pageUrl: input.pageUrl,
    theme: oneOf(input.theme, ["auto", "light", "dark"] as const, "auto", "theme"),
    colors,
    radius: typeof input.radius === "number" && input.radius >= 0 && input.radius <= 40 ? input.radius : undefined,
    fontFamily,
    zIndex: typeof input.zIndex === "number" ? input.zIndex : undefined,
    strings,
    closeDelay,
    images: input.images ?? true,
    capture: input.capture ?? true,
    beforeSubmit: input.beforeSubmit,
  };
}

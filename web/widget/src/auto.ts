/**
 * Start the widget from the script tag alone, with no JavaScript call:
 *
 *   <script type="module" src="https://your-loupebox/widget/v1/loupebox.js" data-key="pk_..."></script>
 *
 * Options are `data-` attributes (see docs/WIDGET.md). Nothing here needs an inline script, so strict page CSPs
 * are fine. A page that wants more control (`beforeSubmit`, `metadata`, custom fields) calls `createWidget`.
 */
import type { FieldMode, WidgetOptions } from "./options";
import { createWidget, type WidgetController } from "./ui";

const STARTED = "data-loupebox-started"; // on the tag itself, so a second copy of this file loaded elsewhere skips it

const text = (el: Element, name: string): string | undefined => el.getAttribute(`data-${name}`)?.trim() || undefined;
const flag = (el: Element, name: string): boolean | undefined => {
  const v = text(el, name);
  return v === undefined ? undefined : !/^(false|0|no|off)$/i.test(v);
};
const num = (el: Element, name: string): number | undefined => {
  const v = Number(text(el, name));
  return text(el, name) !== undefined && Number.isFinite(v) ? v : undefined;
};
const mode = (el: Element, name: string): FieldMode | undefined => {
  const v = text(el, name)?.toLowerCase();
  if (v === undefined) return undefined;
  return v === "required" ? "required" : /^(false|0|no|off)$/.test(v) ? false : "optional";
};

const sameFile = (a: string, b: string) => a.split(/[?#]/)[0] === b.split(/[?#]/)[0];

/** The options a script tag asks for. `url` defaults to `/v1/api` on the origin the script came from. */
function optionsFrom(el: Element, scriptUrl: string): WidgetOptions | null {
  const key = text(el, "key");
  if (!key) return null;
  const fields = { rating: flag(el, "rating"), name: mode(el, "name"), email: mode(el, "email") };
  return {
    url: text(el, "url") ?? `${new URL(scriptUrl).origin}/v1/api`,
    key,
    mode: text(el, "mode") as WidgetOptions["mode"],
    target: text(el, "target"),
    position: text(el, "position") as WidgetOptions["position"],
    theme: text(el, "theme") as WidgetOptions["theme"],
    launcher: flag(el, "launcher"),
    images: flag(el, "images"),
    requireIssueType: flag(el, "require-issue-type"),
    defaultIssueType: text(el, "default-issue-type"),
    closeDelay: num(el, "close-delay"),
    radius: num(el, "radius"),
    zIndex: num(el, "z-index"),
    ...(Object.values(fields).some((v) => v !== undefined) && { fields }),
  };
}

/** Mount a widget for every `<script data-key>` that loaded this file. Returns the ones it started. */
export function autoInit(scriptUrl: string): WidgetController[] {
  if (typeof document === "undefined") return [];
  const started: WidgetController[] = [];
  for (const el of document.querySelectorAll("script[data-key][src]")) {
    if (el.hasAttribute(STARTED) || !sameFile(new URL(el.getAttribute("src") ?? "", document.baseURI).href, scriptUrl)) continue;
    el.setAttribute(STARTED, "");
    const options = optionsFrom(el, scriptUrl);
    if (!options) continue;
    try {
      const widget = createWidget(Object.fromEntries(Object.entries(options).filter(([, v]) => v !== undefined)) as unknown as WidgetOptions);
      started.push(widget);
    } catch (err) {
      console.error("[loupebox] could not start from the script tag", err); // a bad attribute must not break the page
    }
  }
  const first = started[0];
  if (first && typeof window !== "undefined") {
    const w = window as unknown as { loupebox?: WidgetController; dispatchEvent(e: Event): boolean; CustomEvent: typeof CustomEvent };
    w.loupebox ??= first; // for the page's own button: `loupebox.open()`
    w.dispatchEvent(new w.CustomEvent("loupebox:ready", { detail: first }));
  }
  return started;
}

import { createClient, type SubmitResult } from "./client";
import { format } from "./i18n";
import { icon } from "./icons";
import {
  GanymedeConfigError,
  normalizeOptions,
  type ExtraField,
  type MetadataValue,
  type ResolvedOptions,
  type SubmitPayload,
  type WidgetOptions,
} from "./options";
import { css } from "./styles";
import { capabilities, VERSION } from "./version";

export interface WidgetEvents {
  open: undefined;
  close: undefined;
  submit: { id: string; payload: SubmitPayload };
  error: { reason: string; retryAfter?: number };
}

export interface WidgetController {
  open(): void;
  close(): void;
  toggle(): void;
  /** Remove the widget from the page and stop its timers. */
  destroy(): void;
  /** Change options on a live widget (the form is rebuilt, so anything typed is cleared). */
  update(changes: Partial<WidgetOptions>): void;
  /** Listen for `open`, `close`, `submit` or `error`. Returns a function that stops listening. */
  on<E extends keyof WidgetEvents>(event: E, listener: (detail: WidgetEvents[E]) => void): () => void;
  /** True if this version of the script supports a feature (see `capabilities`). */
  supports(feature: string): boolean;
  readonly isOpen: boolean;
  /** The `<ganymede-widget>` element that holds everything. */
  readonly element: HTMLElement;
}

type Child = Node | string | null | false | undefined;

/**
 * Build an element. Attributes are plain strings; `style` and `on*` attributes are refused so nothing
 * here can create inline styles (blocked by strict page CSPs) or inline handlers.
 */
function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | boolean | undefined> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === false) continue;
    if (name === "style" || name.startsWith("on")) throw new Error(`refusing "${name}" attribute`);
    if (name === "class") el.className = String(value);
    else el.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children) if (child) el.append(child);
  return el;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

let counter = 0;

export function createWidget(input: WidgetOptions): WidgetController {
  if (typeof document === "undefined") {
    throw new GanymedeConfigError("createWidget needs a browser (there is no document here)");
  }
  let raw: WidgetOptions = { ...input };
  let opts: ResolvedOptions = normalizeOptions(raw);
  const id = `gm${++counter}`;
  const listeners: { [E in keyof WidgetEvents]: Set<(detail: WidgetEvents[E]) => void> } = {
    open: new Set(), close: new Set(), submit: new Set(), error: new Set(),
  };
  const emit = <E extends keyof WidgetEvents>(event: E, detail: WidgetEvents[E]) => {
    for (const fn of listeners[event]) {
      try {
        fn(detail);
      } catch (err) {
        console.error("[ganymede] listener threw", err); // a broken listener must not break the widget
      }
    }
  };

  const host = document.createElement("ganymede-widget");
  const shadow = host.attachShadow({ mode: "open" });
  let isOpen = false;
  let busy = false;
  let destroyed = false;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;
  let selectedType: string | undefined;
  let rating = 0;

  // Refs filled by render().
  let launcher: HTMLButtonElement | null = null;
  let panel!: HTMLElement;
  let form!: HTMLFormElement;
  let doneBox!: HTMLElement;
  let statusEl!: HTMLElement;
  let submitBtn!: HTMLButtonElement;

  const client = () => createClient({ url: opts.url, key: opts.key });

  function applyTheme(): void {
    host.setAttribute("data-theme", opts.theme);
    const set = (name: string, value: string | undefined) =>
      value === undefined ? host.style.removeProperty(name) : host.style.setProperty(name, value); // CSSOM: allowed under strict CSP
    set("--gm-accent", opts.colors.accent);
    set("--gm-accent-text", opts.colors.accentText);
    set("--gm-bg", opts.colors.background);
    set("--gm-text", opts.colors.text);
    set("--gm-muted", opts.colors.muted);
    set("--gm-border", opts.colors.border);
    set("--gm-radius", opts.radius === undefined ? undefined : `${opts.radius}px`);
    set("--gm-font", opts.fontFamily);
    set("--gm-z", opts.zIndex === undefined ? undefined : String(opts.zIndex));
  }

  function applyStyles(): void {
    if ("adoptedStyleSheets" in shadow && typeof CSSStyleSheet !== "undefined" && "replaceSync" in CSSStyleSheet.prototype) {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(css);
      shadow.adoptedStyleSheets = [sheet];
    } else {
      shadow.append(h("style", {}, css));
    }
  }

  // --- fields ---------------------------------------------------------------------------------

  function label(text: string, forId: string, mode?: string): HTMLLabelElement {
    return h("label", { for: forId }, text, mode === "optional" && h("span", { class: "hint" }, ` (${opts.strings.optional})`));
  }

  function errorFor(fieldId: string): HTMLElement {
    return h("p", { class: "err", id: `${id}-${fieldId}-err`, hidden: true });
  }

  function typeBadges(): HTMLElement | null {
    if (opts.issueTypes.length === 0) return null;
    const group = h("div", { class: "types", role: "radiogroup", "aria-labelledby": `${id}-types-l` });
    const buttons: HTMLButtonElement[] = [];
    const select = (typeId: string | undefined, focus = false) => {
      selectedType = typeId;
      buttons.forEach((b) => {
        const on = b.dataset.id === typeId;
        b.setAttribute("aria-checked", String(on));
        b.tabIndex = on || (typeId === undefined && b === buttons[0]) ? 0 : -1;
        if (on && focus) b.focus();
      });
      setFieldError("type", "");
    };
    for (const type of opts.issueTypes) {
      const builtIn = icon(type.id);
      const button = h(
        "button",
        { type: "button", class: "type", role: "radio", "aria-checked": "false", "data-id": type.id },
        builtIn ?? (type.icon && h("span", { class: "emoji", "aria-hidden": "true" }, type.icon)),
        type.label,
      );
      if (type.color) button.style.setProperty("--gm-type", type.color);
      button.addEventListener("click", () => select(selectedType === type.id && !opts.requireIssueType ? undefined : type.id));
      button.addEventListener("keydown", (e) => {
        const i = buttons.indexOf(button);
        const move = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (move) {
          e.preventDefault();
          select(buttons[(i + move + buttons.length) % buttons.length].dataset.id, true);
        } else if (e.key === "Home" || e.key === "End") {
          e.preventDefault();
          select(buttons[e.key === "Home" ? 0 : buttons.length - 1].dataset.id, true);
        }
      });
      buttons.push(button);
      group.append(button);
    }
    select(opts.defaultIssueType);
    return h(
      "fieldset",
      {},
      h("legend", { id: `${id}-types-l` }, opts.strings.issueTypeLabel, !opts.requireIssueType && h("span", { class: "hint" }, ` (${opts.strings.optional})`)),
      group,
      errorFor("type"),
    );
  }

  function ratingField(): HTMLElement | null {
    if (!opts.fields.rating) return null;
    const group = h("div", { class: "rating", role: "radiogroup", "aria-labelledby": `${id}-rating-l` });
    const stars: HTMLButtonElement[] = [];
    const paint = () => stars.forEach((s, i) => {
      s.setAttribute("data-on", String(i < rating));
      s.setAttribute("aria-checked", String(i + 1 === rating));
      s.tabIndex = i + 1 === rating || (rating === 0 && i === 0) ? 0 : -1;
    });
    for (let n = 1; n <= 5; n++) {
      const star = h("button", { type: "button", class: "star", role: "radio", "aria-checked": "false", "aria-label": `${n} / 5` }, "★");
      star.addEventListener("click", () => { rating = rating === n ? 0 : n; paint(); });
      star.addEventListener("keydown", (e) => {
        const move = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
        if (move) {
          e.preventDefault();
          rating = Math.min(5, Math.max(1, (rating || 0) + move));
          paint();
          stars[rating - 1].focus();
        }
      });
      stars.push(star);
      group.append(star);
    }
    paint();
    return h("fieldset", {}, h("legend", { id: `${id}-rating-l` }, opts.strings.ratingLabel, h("span", { class: "hint" }, ` (${opts.strings.optional})`)), group, errorFor("rating"));
  }

  function textField(fieldId: string, text: string, type: "text" | "email", mode: "optional" | "required", autocomplete: string): HTMLElement {
    const input = h("input", { type, id: `${id}-${fieldId}`, name: fieldId, autocomplete, maxlength: type === "email" ? "320" : "120", "aria-describedby": `${id}-${fieldId}-err` });
    if (mode === "required") input.required = false; // validated by us, so messages are ours
    return h("div", {}, label(text, `${id}-${fieldId}`, mode), input, errorFor(fieldId));
  }

  function extraField(field: ExtraField): HTMLElement {
    const fid = `${id}-x-${field.id}`;
    const common = { id: fid, name: field.id, "aria-describedby": `${fid}-err`, "data-extra": field.id };
    let control: HTMLElement;
    if (field.type === "textarea") control = h("textarea", { ...common, maxlength: String(field.maxLength ?? 256) });
    else if (field.type === "select") {
      control = h("select", common, h("option", { value: "" }, ""), ...(field.options ?? []).map((o) => h("option", { value: o }, o)));
    } else if (field.type === "checkbox") {
      control = h("input", { ...common, type: "checkbox" });
      return h("div", {}, h("label", { class: "check", for: fid }, control, field.label), h("p", { class: "err", id: `${fid}-err`, hidden: true }));
    } else control = h("input", { ...common, type: "text", maxlength: String(field.maxLength ?? 256) });
    return h("div", {}, label(field.label, fid, field.required ? undefined : "optional"), control, h("p", { class: "err", id: `${fid}-err`, hidden: true }));
  }

  // --- validation and status ------------------------------------------------------------------

  function setFieldError(fieldId: string, message: string): void {
    const err = shadow.getElementById(`${id}-${fieldId}-err`);
    const input = shadow.getElementById(`${id}-${fieldId}`) ?? shadow.getElementById(`${id}-x-${fieldId}`);
    if (err) {
      err.textContent = message;
      err.hidden = !message;
    }
    if (input) {
      if (message) input.setAttribute("aria-invalid", "true");
      else input.removeAttribute("aria-invalid");
    }
  }

  function setStatus(message: string, kind: "error" | "info" = "info"): void {
    statusEl.textContent = message;
    statusEl.setAttribute("data-kind", kind);
  }

  const read = (fieldId: string) => (shadow.getElementById(`${id}-${fieldId}`) as HTMLInputElement | null)?.value.trim() ?? "";

  function validate(): { ok: true; payload: SubmitPayload } | { ok: false; first: string } {
    const s = opts.strings;
    const errors: Record<string, string> = {};
    const message = read("message");
    if (!message) errors.message = s.required;
    if (opts.requireIssueType && opts.issueTypes.length && !selectedType) errors.type = s.chooseType;
    const name = read("name");
    const email = read("email");
    if (opts.fields.name === "required" && !name) errors.name = s.required;
    if (opts.fields.email === "required" && !email) errors.email = s.required;
    else if (email && !EMAIL.test(email)) errors.email = s.invalidEmail;

    const metadata: Record<string, MetadataValue> = {};
    try {
      const host = typeof opts.metadata === "function" ? opts.metadata() : opts.metadata;
      Object.assign(metadata, host ?? {});
    } catch (err) {
      console.error("[ganymede] the metadata function threw; sending without it", err);
    }
    for (const field of opts.extraFields) {
      const el = shadow.querySelector<HTMLInputElement>(`[data-extra="${field.id}"]`);
      const value: MetadataValue = field.type === "checkbox" ? Boolean(el?.checked) : (el?.value.trim() ?? "");
      if (field.required && (value === "" || value === false)) errors[`x-${field.id}`] = s.required;
      if (value !== "") metadata[field.id] = value;
    }

    for (const fid of ["message", "type", "name", "email", "rating", ...opts.extraFields.map((f) => `x-${f.id}`)]) {
      const target = fid.startsWith("x-") ? fid.slice(2) : fid;
      setFieldError(fid.startsWith("x-") ? `x-${target}` : fid, errors[fid] ?? "");
    }
    const first = Object.keys(errors)[0];
    if (first) return { ok: false, first };
    return {
      ok: true,
      payload: {
        message, metadata,
        ...(rating ? { rating } : {}),
        ...(name ? { name } : {}),
        ...(email ? { email } : {}),
        ...(selectedType ? { issueType: selectedType } : {}),
      },
    };
  }

  function focusField(fieldId: string): void {
    const el = shadow.getElementById(`${id}-${fieldId}`) ?? shadow.getElementById(`${id}-x-${fieldId.replace(/^x-/, "")}`)
      ?? shadow.querySelector<HTMLElement>(fieldId === "type" ? ".type" : fieldId === "rating" ? ".star" : "");
    el?.focus();
  }

  // --- submit ---------------------------------------------------------------------------------

  function failureText(result: Exclude<SubmitResult, { ok: true }>): string {
    const s = opts.strings;
    switch (result.reason) {
      case "network": return s.errorNetwork;
      case "invalid": return s.errorInvalid;
      case "rate_limited": return format(s.errorRateLimited, { seconds: result.retryAfter ?? 60 });
      case "challenge_unsupported": return s.errorChallenge;
      default: return s.errorRejected;
    }
  }

  async function submit(event: Event): Promise<void> {
    event.preventDefault();
    if (busy) return;
    const checked = validate();
    if (!checked.ok) {
      focusField(checked.first);
      return;
    }
    let payload = checked.payload;
    if (opts.beforeSubmit) {
      try {
        const changed = await opts.beforeSubmit(payload);
        if (changed === false) return;
        payload = changed;
      } catch (err) {
        console.error("[ganymede] beforeSubmit threw; nothing was sent", err);
        return;
      }
    }
    busy = true;
    submitBtn.disabled = true;
    submitBtn.textContent = opts.strings.sending;
    form.setAttribute("aria-busy", "true");
    setStatus("");

    const honeypot = (shadow.getElementById(`${id}-website`) as HTMLInputElement | null)?.value ?? "";
    const pageUrl = typeof opts.pageUrl === "function" ? opts.pageUrl() : opts.pageUrl;
    const result = await client().submit({ ...payload, website: honeypot, pageUrl });

    busy = false;
    submitBtn.disabled = false;
    submitBtn.textContent = opts.strings.submit;
    form.removeAttribute("aria-busy");
    if (destroyed) return;

    if (result.ok) {
      emit("submit", { id: result.id, payload });
      showDone();
      return;
    }
    if (result.fields) {
      const known = { message: "message", email: "email", name: "name", rating: "rating" } as const;
      for (const [field, message] of Object.entries(result.fields)) {
        if (field in known) setFieldError(known[field as keyof typeof known], message);
      }
    }
    setStatus(failureText(result), "error");
    emit("error", { reason: result.reason, retryAfter: result.retryAfter });
  }

  function showDone(): void {
    form.hidden = true;
    doneBox.hidden = false;
    doneBox.querySelector<HTMLElement>(".again")?.focus();
    if (opts.mode === "floating" && opts.closeDelay > 0) {
      closeTimer = setTimeout(() => close(), opts.closeDelay);
    }
  }

  function resetForm(): void {
    form.reset();
    rating = 0;
    form.hidden = false;
    doneBox.hidden = true;
    setStatus("");
    render(); // simplest way to reset badge/rating/error state together
  }

  // --- render ---------------------------------------------------------------------------------

  function render(): void {
    shadow.replaceChildren();
    applyStyles();
    applyTheme();

    const title = h("h2", { id: `${id}-title` }, opts.strings.title);
    const closeBtn = opts.mode === "floating"
      ? h("button", { type: "button", class: "close", "aria-label": opts.strings.close }, icon("close"))
      : null;
    closeBtn?.addEventListener("click", () => close());

    statusEl = h("p", { class: "status", role: "status", "aria-live": "polite" });
    submitBtn = h("button", { type: "submit", class: "submit" }, opts.strings.submit);
    selectedType = undefined;
    rating = 0;

    form = h(
      "form",
      { novalidate: true, "aria-labelledby": `${id}-title` },
      typeBadges(),
      h(
        "div", {},
        label(opts.strings.messageLabel, `${id}-message`),
        h("textarea", { id: `${id}-message`, name: "message", maxlength: "5000", placeholder: opts.strings.messagePlaceholder, "aria-describedby": `${id}-message-err` }),
        errorFor("message"),
      ),
      ratingField(),
      opts.fields.name ? textField("name", opts.strings.nameLabel, "text", opts.fields.name, "name") : null,
      opts.fields.email ? textField("email", opts.strings.emailLabel, "email", opts.fields.email, "email") : null,
      ...opts.extraFields.map(extraField),
      // Honeypot: off-screen, not display:none (some bots skip those), unlabeled for assistive tech.
      h("div", { class: "honeypot", "aria-hidden": "true" }, h("input", { type: "text", id: `${id}-website`, name: "website", tabindex: "-1", autocomplete: "off" })),
      statusEl,
      submitBtn,
    );
    form.addEventListener("submit", (e) => void submit(e));

    const again = h("button", { type: "button", class: "again" }, opts.strings.sendAnother);
    again.addEventListener("click", resetForm);
    doneBox = h(
      "div", { class: "done", role: "status", hidden: true },
      h("div", { class: "tick", "aria-hidden": "true" }, "✓"),
      h("h3", {}, opts.strings.thanksTitle),
      h("p", {}, opts.strings.thanks),
      opts.mode === "inline" || opts.closeDelay === 0 ? again : null,
    );

    panel = h(
      "div",
      { class: "panel", role: opts.mode === "floating" ? "dialog" : "group", "aria-labelledby": `${id}-title`, hidden: opts.mode === "floating" && !isOpen },
      h("div", { class: "head" }, title, closeBtn),
      form,
      doneBox,
    );
    panel.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && opts.mode === "floating") {
        e.stopPropagation();
        close();
      }
    });

    launcher = null;
    if (opts.mode === "floating" && opts.launcher) {
      launcher = h(
        "button",
        { type: "button", class: "launcher", "aria-haspopup": "dialog", "aria-expanded": String(isOpen), "aria-controls": `${id}-panel` },
        icon("chat"),
        opts.strings.launcher,
      );
      launcher.addEventListener("click", () => toggle());
    }
    panel.id = `${id}-panel`;
    shadow.append(h("div", { "data-mode": opts.mode, "data-position": opts.position }, launcher, panel));
  }

  // --- open / close ---------------------------------------------------------------------------

  function open(): void {
    if (isOpen || destroyed || opts.mode !== "floating") return;
    clearTimeout(closeTimer);
    isOpen = true;
    if (!doneBox.hidden) resetForm();
    panel.hidden = false;
    launcher?.setAttribute("aria-expanded", "true");
    (shadow.querySelector<HTMLElement>("textarea, .type") ?? panel).focus();
    emit("open", undefined);
  }

  function close(): void {
    if (!isOpen || destroyed) return;
    clearTimeout(closeTimer);
    isOpen = false;
    panel.hidden = true;
    launcher?.setAttribute("aria-expanded", "false");
    if (shadow.activeElement && panel.contains(shadow.activeElement)) launcher?.focus();
    emit("close", undefined);
  }

  function toggle(): void {
    if (isOpen) close();
    else open();
  }

  // --- mount ----------------------------------------------------------------------------------

  render();
  const mount = () => {
    if (destroyed) return;
    if (opts.mode === "inline") {
      const target = typeof opts.target === "string" ? document.querySelector(opts.target) : opts.target;
      if (!target) throw new GanymedeConfigError(`inline "target" was not found: ${String(opts.target)}`);
      target.append(host);
    } else {
      document.body.append(host);
    }
  };
  if (opts.mode === "floating" && document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }

  return {
    open,
    close,
    toggle,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      clearTimeout(closeTimer);
      host.remove();
      for (const set of Object.values(listeners)) set.clear();
    },
    update(changes) {
      raw = { ...raw, ...changes };
      opts = normalizeOptions(raw);
      render();
    },
    on(event, listener) {
      (listeners[event] as Set<typeof listener>).add(listener);
      return () => void (listeners[event] as Set<typeof listener>).delete(listener);
    },
    supports: (feature) => capabilities.includes(feature),
    get isOpen() {
      return isOpen;
    },
    element: host,
  };
}

export { VERSION };

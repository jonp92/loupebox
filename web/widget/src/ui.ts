import { createClient, type SubmitResult } from "./client";
import { canCapture, captureFrame } from "./capture";
import { h } from "./dom";
import { fromExtra, localize, type FieldSpec, type SiteField } from "./fields";
import { format } from "./i18n";
import { icon } from "./icons";
import { IMAGE_TYPES, prepareImage, type ImageLimits } from "./images";
import {
  LoupeboxConfigError,
  normalizeOptions,
  type MetadataValue,
  type ResolvedOptions,
  type SubmitPayload,
  type WidgetOptions,
} from "./options";
import { openRedactor } from "./redact";
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
  /** The `<loupebox-widget>` element that holds everything. */
  readonly element: HTMLElement;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

let counter = 0;

export function createWidget(input: WidgetOptions): WidgetController {
  if (typeof document === "undefined") {
    throw new LoupeboxConfigError("createWidget needs a browser (there is no document here)");
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
        console.error("[loupebox] listener threw", err); // a broken listener must not break the widget
      }
    }
  };

  const host = document.createElement("loupebox-widget");
  const shadow = host.attachShadow({ mode: "open" });
  let isOpen = false;
  let busy = false;
  let destroyed = false;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;
  let selectedType: string | undefined;
  let rating = 0;
  let limits: ImageLimits | null = null; // what the site accepts; null while unknown or when images are off
  let siteFields: SiteField[] = []; // the questions from the site's settings, once its config has arrived
  let configReady: Promise<void> | null = null; // set once the site's config has been asked for
  const picked: { file: Blob; name: string; url: string }[] = [];
  let capturing = false; // the browser's share picker or the redact editor is open
  let closeEditor: (() => void) | null = null;

  // Refs filled by render().
  let launcher: HTMLButtonElement | null = null;
  let panel!: HTMLElement;
  let form!: HTMLFormElement;
  let doneBox!: HTMLElement;
  let statusEl!: HTMLElement;
  let submitBtn!: HTMLButtonElement;
  let imageSlot!: HTMLElement;
  let fieldSlot!: HTMLElement;

  // One client per site, so what it learns from the config (the metadata limit) is used when it submits.
  let cached: { url: string; key: string; client: ReturnType<typeof createClient> } | null = null;
  const client = () => {
    if (!cached || cached.url !== opts.url || cached.key !== opts.key) {
      cached = { url: opts.url, key: opts.key, client: createClient({ url: opts.url, key: opts.key }) };
    }
    return cached.client;
  };

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

  /** The site's fields in the visitor's language, then the page's own `extraFields` the site has not claimed. */
  function fieldSpecs(): FieldSpec[] {
    const site = siteFields.map((f) => localize(f, opts.locale));
    const taken = new Set(site.map((f) => f.id));
    return [...site, ...opts.extraFields.map(fromExtra).filter((f) => !taken.has(f.id))];
  }

  function extraField(field: FieldSpec): HTMLElement {
    const fid = `${id}-x-${field.id}`;
    const common = { id: fid, name: field.id, "aria-describedby": `${fid}-err`, "data-extra": field.id };
    let control: HTMLElement;
    if (field.type === "textarea") control = h("textarea", { ...common, maxlength: String(field.maxLength ?? 256) });
    else if (field.type === "select") {
      control = h("select", common, h("option", { value: "" }, ""), ...field.options.map((o) => h("option", { value: o.value }, o.label)));
    } else if (field.type === "checkbox") {
      control = h("input", { ...common, type: "checkbox" });
      return h("div", {}, h("label", { class: "check", for: fid }, control, field.label), h("p", { class: "err", id: `${fid}-err`, hidden: true }));
    } else control = h("input", { ...common, type: "text", maxlength: String(field.maxLength ?? 256) });
    return h("div", {}, label(field.label, fid, field.required ? undefined : "optional"), control, h("p", { class: "err", id: `${fid}-err`, hidden: true }));
  }

  // --- images ---------------------------------------------------------------------------------

  let paintImages: () => void = () => {};

  function clearImages(): void {
    for (const p of picked) URL.revokeObjectURL(p.url);
    picked.length = 0;
    paintImages();
  }

  async function addImages(files: File[]): Promise<void> {
    if (!limits || busy) return;
    const s = opts.strings;
    setFieldError("images", "");
    for (const file of files) {
      if (picked.length >= limits.maxCount) {
        setFieldError("images", format(s.errorImageCount, { max: limits.maxCount }));
        break;
      }
      const out = await prepareImage(file, limits);
      if (typeof out === "string") {
        const mb = Math.round(limits.maxBytes / 1048576);
        setFieldError("images", out === "type" ? s.errorImageType : format(s.errorImageSize, { mb }));
        continue;
      }
      const name = file.name || "image";
      const named = typeof File === "function" && !(out instanceof File) ? new File([out], name, { type: out.type }) : out;
      picked.push({ file: named, name, url: URL.createObjectURL(named) });
    }
    paintImages();
  }

  /** Share the screen, take one frame, let the visitor black out private parts, and attach the result. */
  async function captureAndEdit(): Promise<void> {
    if (!limits || busy || capturing) return;
    const s = opts.strings;
    capturing = true;
    setFieldError("images", "");
    setStatus("");
    paintImages();
    try {
      // The widget hides itself for the moment the frame is taken, so it is not in the picture.
      const shot = await captureFrame({
        beforeGrab: () => host.setAttribute("data-capturing", ""),
        afterGrab: () => host.removeAttribute("data-capturing"),
      });
      if (destroyed) return;
      if (!shot.ok) {
        if (shot.reason === "failed") setStatus(s.captureFailed, "error"); // cancelling the picker is not an error
        return;
      }
      const editor = openRedactor({ frame: shot.frame, strings: s, limits, mount: shadow, id });
      closeEditor = editor.cancel;
      const out = await editor.result;
      closeEditor = null;
      if (destroyed || out === null) return;
      if (out === "size") {
        setFieldError("images", format(s.errorImageSize, { mb: Math.round(limits.maxBytes / 1048576) }));
      } else if (picked.length >= limits.maxCount) {
        setFieldError("images", format(s.errorImageCount, { max: limits.maxCount }));
      } else {
        const name = `screenshot.${out.type === "image/png" ? "png" : "jpg"}`;
        const file = typeof File === "function" ? new File([out], name, { type: out.type }) : out;
        picked.push({ file, name, url: URL.createObjectURL(file) });
      }
    } finally {
      capturing = false;
      if (!destroyed) {
        paintImages();
        shadow.querySelector<HTMLButtonElement>(".capture-image")?.focus();
      }
    }
  }

  /** The "Add image" button, the thumbnails and their messages. Built once the site is known to accept images. */
  function mountImages(): void {
    imageSlot.replaceChildren();
    imageSlot.hidden = !limits || !opts.images;
    if (!limits || !opts.images) return;
    const max = limits.maxCount;
    const s = opts.strings;
    const input = h("input", { type: "file", accept: IMAGE_TYPES.join(","), multiple: true, hidden: true, tabindex: "-1" });
    const add = h("button", { type: "button", class: "add-image", "aria-describedby": `${id}-images-hint` }, icon("image"), s.addImage);
    // Only where the browser can share a screen (desktops, secure pages), when the page has not turned it off.
    const capture = opts.capture && canCapture()
      ? h("button", { type: "button", class: "add-image capture-image", "aria-describedby": `${id}-images-hint` }, icon("capture"), s.captureButton)
      : null;
    const count = h("span", { class: "hint", "aria-live": "polite" });
    const list = h("ul", { class: "thumbs", "aria-label": s.imagesLabel });
    add.addEventListener("click", () => input.click());
    capture?.addEventListener("click", () => void captureAndEdit());
    input.addEventListener("change", () => {
      const files = [...(input.files ?? [])];
      input.value = ""; // so choosing the same file again still fires
      void addImages(files);
    });
    paintImages = () => {
      list.hidden = picked.length === 0;
      add.disabled = picked.length >= max;
      if (capture) capture.disabled = capturing || picked.length >= max;
      count.textContent = picked.length ? format(s.imageCount, { count: picked.length, max }) : "";
      list.replaceChildren(...picked.map((p, i) => {
        // The preview needs `img-src blob:` on strict pages; without it the picture is replaced by an icon.
        const img = h("img", { src: p.url, alt: p.name });
        img.addEventListener("error", () => img.replaceWith(icon("image") ?? p.name));
        const remove = h("button", { type: "button", class: "remove", "aria-label": format(s.removeImage, { n: i + 1 }) }, icon("close"));
        remove.addEventListener("click", () => {
          if (busy) return;
          URL.revokeObjectURL(p.url);
          picked.splice(picked.indexOf(p), 1);
          setFieldError("images", "");
          paintImages();
          add.focus();
        });
        return h("li", {}, img, remove);
      }));
    };
    imageSlot.append(
      h("div", { class: "image-row" }, add, capture, input, count),
      list,
      h("p", { class: "hint", id: `${id}-images-hint` }, s.imageHint),
      errorFor("images"),
    );
    paintImages();
  }

  /** The site's questions, built once the site is known. A page's own field with the same id steps aside. */
  function mountFields(): void {
    fieldSlot.replaceChildren(...siteFields.map((f) => extraField(localize(f, opts.locale))));
    for (const f of siteFields) shadow.querySelector(`[data-host="${f.id}"]`)?.remove();
  }

  function loadConfig(): void {
    if (configReady || destroyed) return;
    configReady = client().config().then((found) => {
      if (destroyed) return;
      limits = opts.images ? found.images : null;
      siteFields = found.fields;
      mountImages();
      mountFields();
    });
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
      console.error("[loupebox] the metadata function threw; sending without it", err);
    }
    const specs = fieldSpecs();
    for (const field of specs) {
      const el = shadow.querySelector<HTMLInputElement>(`[data-extra="${field.id}"]`);
      const value: MetadataValue = field.type === "checkbox" ? Boolean(el?.checked) : (el?.value.trim() ?? "");
      if (field.required && (value === "" || value === false)) errors[`x-${field.id}`] = s.required;
      if (value !== "") metadata[field.id] = value;
    }

    for (const fid of ["message", "type", "name", "email", "rating", ...specs.map((f) => `x-${f.id}`)]) {
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
    if (configReady) await configReady; // the site's questions may still be on their way
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
        console.error("[loupebox] beforeSubmit threw; nothing was sent", err);
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
    const result = await client().submit({ ...payload, website: honeypot, pageUrl, images: picked.map((p) => p.file) });

    busy = false;
    submitBtn.disabled = false;
    submitBtn.textContent = opts.strings.submit;
    form.removeAttribute("aria-busy");
    if (destroyed) return;

    if (result.ok) {
      clearImages();
      emit("submit", { id: result.id, payload });
      showDone();
      return;
    }
    if (result.fields) {
      const known = { message: "message", email: "email", name: "name", rating: "rating", images: "images" } as const;
      const asked = new Set(fieldSpecs().map((f) => f.id));
      for (const [field, message] of Object.entries(result.fields)) {
        if (field in known) setFieldError(known[field as keyof typeof known], message);
        else if (asked.has(field)) setFieldError(`x-${field}`, opts.strings.required); // the server's text is English
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
    clearImages();
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
    imageSlot = h("div", { class: "images", hidden: true });
    fieldSlot = h("div", { class: "site-fields" });

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
      imageSlot,
      ratingField(),
      opts.fields.name ? textField("name", opts.strings.nameLabel, "text", opts.fields.name, "name") : null,
      opts.fields.email ? textField("email", opts.strings.emailLabel, "email", opts.fields.email, "email") : null,
      fieldSlot,
      ...opts.extraFields.map((f) => {
        const wrap = extraField(fromExtra(f));
        wrap.setAttribute("data-host", f.id); // removed if the site defines a field with the same id
        return wrap;
      }),
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
    // Paste or drop an image anywhere on the form. Text pastes and unrelated drops are left alone.
    panel.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files ?? [])].filter((f) => f.type.startsWith("image/"));
      if (!limits || !files.length) return;
      e.preventDefault();
      void addImages(files);
    });
    const carriesFiles = (e: DragEvent) => [...(e.dataTransfer?.types ?? [])].includes("Files");
    panel.addEventListener("dragover", (e) => {
      if (!limits || !carriesFiles(e)) return;
      e.preventDefault();
      panel.setAttribute("data-dragging", "true");
    });
    panel.addEventListener("dragleave", (e) => {
      if (!panel.contains(e.relatedTarget as Node | null)) panel.removeAttribute("data-dragging");
    });
    panel.addEventListener("drop", (e) => {
      panel.removeAttribute("data-dragging");
      if (!limits || !carriesFiles(e)) return;
      e.preventDefault();
      void addImages([...(e.dataTransfer?.files ?? [])]);
    });
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
    mountImages();
    mountFields();
  }

  // --- open / close ---------------------------------------------------------------------------

  function open(): void {
    if (isOpen || destroyed || opts.mode !== "floating") return;
    clearTimeout(closeTimer);
    isOpen = true;
    loadConfig();
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
      if (!target) throw new LoupeboxConfigError(`inline "target" was not found: ${String(opts.target)}`);
      target.append(host);
    } else {
      document.body.append(host);
    }
  };
  if (opts.mode === "inline") loadConfig();
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
      closeEditor?.();
      clearImages();
      host.remove();
      for (const set of Object.values(listeners)) set.clear();
    },
    update(changes) {
      closeEditor?.(); // the form is rebuilt, which would strand an open editor
      raw = { ...raw, ...changes };
      opts = normalizeOptions(raw);
      if ("url" in changes || "key" in changes || "images" in changes) {
        limits = null; // another site may take different things
        siteFields = [];
        configReady = null;
        clearImages();
      }
      render();
      if (isOpen || opts.mode === "inline") loadConfig();
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

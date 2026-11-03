import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { BUNDLE, captureWarnings, mockFetch, ok, setupDom, teardownDom, until, wait } from "./helpers.mjs";

const g = await import(BUNDLE.href);
const URL_ = "https://feedback.example.com/v1/api";
const OFF = { status: 200, body: { mode: "off" } };

let widgets = [];
let originalFetch;

/** Mount a widget with a mocked network. `handler` answers /feedback (default: accepted). */
function mount(options = {}, handler = () => ok()) {
  const fetch = mockFetch((call) => (call.url.endsWith("/challenge") ? OFF : handler(call)));
  globalThis.fetch = fetch;
  const w = g.createWidget({ url: URL_, key: "pk_test", closeDelay: 0, ...options });
  widgets.push(w);
  const root = w.element.shadowRoot;
  const q = (sel) => root.querySelector(sel);
  const all = (sel) => [...root.querySelectorAll(sel)];
  const sent = () => fetch.calls.filter((c) => c.url.endsWith("/feedback")).map((c) => c.body);
  const type = (sel, value) => {
    const el = q(sel);
    el.value = value;
    el.dispatchEvent(new window.Event("input", { bubbles: true }));
  };
  const submit = () => q("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  return { w, root, q, all, fetch, sent, type, submit, launcher: q(".launcher") };
}

beforeEach(() => {
  globalThis.window = setupDom().window;
  originalFetch = globalThis.fetch;
});
afterEach(() => {
  widgets.forEach((w) => w.destroy());
  widgets = [];
  globalThis.fetch = originalFetch;
  teardownDom();
  delete globalThis.window;
});

describe("floating widget", () => {
  it("renders a launcher and a hidden dialog, and opens and closes with events", () => {
    const { w, q, launcher } = mount();
    const events = [];
    w.on("open", () => events.push("open"));
    w.on("close", () => events.push("close"));
    assert.equal(w.element.tagName.toLowerCase(), "loupebox-widget");
    assert.ok(w.element.isConnected);
    assert.equal(launcher.getAttribute("aria-expanded"), "false");
    assert.equal(q(".panel").hidden, true);
    assert.equal(q(".panel").getAttribute("role"), "dialog");

    launcher.click();
    assert.equal(q(".panel").hidden, false);
    assert.equal(launcher.getAttribute("aria-expanded"), "true");
    assert.equal(w.isOpen, true);
    assert.equal(w.element.shadowRoot.activeElement?.tagName, "BUTTON"); // first badge gets focus
    launcher.click();
    assert.deepEqual(events, ["open", "close"]);
    assert.equal(q(".panel").hidden, true);
  });

  it("closes on Escape and gives focus back to the launcher", () => {
    const { w, q, launcher } = mount();
    w.open();
    q("textarea").focus();
    q(".panel").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    assert.equal(w.isOpen, false);
    assert.equal(w.element.shadowRoot.activeElement, launcher);
  });

  it("can run without its own button (launcher: false) and be driven from the page", () => {
    const { w, q } = mount({ launcher: false });
    assert.equal(q(".launcher"), null);
    w.open();
    assert.equal(q(".panel").hidden, false);
    w.toggle();
    assert.equal(w.isOpen, false);
  });

  it("positions left or right and uses distinct ids for several widgets", () => {
    const a = mount({ position: "bottom-left" });
    const b = mount();
    assert.equal(a.q("[data-position]").getAttribute("data-position"), "bottom-left");
    assert.notEqual(a.q("textarea").id, b.q("textarea").id);
  });

  it("destroy removes it from the page and silences listeners", () => {
    const { w } = mount();
    let opened = 0;
    w.on("open", () => opened++);
    w.destroy();
    assert.equal(w.element.isConnected, false);
    w.open();
    assert.equal(opened, 0);
    w.destroy(); // twice is fine
  });
});

describe("issue type badges", () => {
  it("offers bug, idea, question and praise as an accessible radio group", () => {
    const { all, q } = mount();
    const radios = all(".type");
    assert.deepEqual(radios.map((r) => r.textContent.trim()), ["Bug", "Idea", "Question", "Praise"]);
    assert.ok(radios.every((r) => r.getAttribute("role") === "radio" && r.getAttribute("aria-checked") === "false"));
    assert.equal(q(".types").getAttribute("role"), "radiogroup");
    assert.ok(radios.every((r) => r.querySelector("svg")), "built-in types have drawn icons");
    assert.deepEqual(radios.map((r) => r.tabIndex), [0, -1, -1, -1]); // roving tabindex
  });

  it("selects on click, deselects on a second click, and moves with the arrow keys", () => {
    const { all } = mount();
    const [bug, idea, , praise] = all(".type");
    const checked = () => all(".type").filter((r) => r.getAttribute("aria-checked") === "true").map((r) => r.dataset.id);
    bug.click();
    assert.deepEqual(checked(), ["bug"]);
    bug.click();
    assert.deepEqual(checked(), []);
    bug.click();
    bug.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    assert.deepEqual(checked(), ["idea"]);
    assert.equal(idea.tabIndex, 0);
    idea.dispatchEvent(new window.KeyboardEvent("keydown", { key: "End", bubbles: true }));
    assert.deepEqual(checked(), ["praise"]);
    praise.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    assert.deepEqual(checked(), ["bug"]); // wraps
  });

  it("sends the choice as metadata.issue_type", async () => {
    const { all, type, submit, sent } = mount();
    all(".type")[0].click();
    type("textarea", "It crashes");
    submit();
    await until(() => sent().length);
    assert.equal(sent()[0].metadata.issue_type, "bug");
    assert.equal(sent()[0].metadata.widget_version, g.VERSION);
  });

  it("sends no issue_type when none was picked, unless a default is set", async () => {
    const none = mount();
    none.type("textarea", "hello");
    none.submit();
    await until(() => none.sent().length);
    assert.ok(!("issue_type" in none.sent()[0].metadata));

    const preset = mount({ defaultIssueType: "idea" });
    assert.equal(preset.all(".type").find((r) => r.dataset.id === "idea").getAttribute("aria-checked"), "true");
    preset.type("textarea", "hello");
    preset.submit();
    await until(() => preset.sent().length);
    assert.equal(preset.sent()[0].metadata.issue_type, "idea");
  });

  it("supports custom types, with labels and icons shown as text, never as markup", () => {
    const evil = `<img src=x onerror="window.pwned=1">`;
    const { all, q, root } = mount({
      issueTypes: [{ id: "billing", label: evil, icon: "💳", color: "#2b6cb0" }, { id: "other", label: "Something else" }],
    });
    const [billing, other] = all(".type");
    assert.equal(billing.textContent.trim().endsWith(evil), true);
    assert.equal(root.querySelector("img"), null);
    assert.equal(window.pwned, undefined);
    assert.equal(billing.querySelector(".emoji").textContent, "💳");
    assert.equal(billing.style.getPropertyValue("--gm-type"), "#2b6cb0");
    assert.equal(other.querySelector("svg"), null);
    assert.equal(q(".type[data-id='billing']"), billing);
  });

  it("can be required, or turned off entirely", async () => {
    const required = mount({ requireIssueType: true });
    required.type("textarea", "hi");
    required.submit();
    assert.equal(required.sent().length, 0);
    assert.match(required.q("[id$='-type-err']").textContent, /choose a type/i);
    required.all(".type")[1].click();
    required.all(".type")[1].click(); // can't deselect a required choice
    assert.equal(required.all(".type")[1].getAttribute("aria-checked"), "true");

    const none = mount({ issueTypes: false });
    assert.equal(none.q(".types"), null);
    none.type("textarea", "hi");
    none.submit();
    await until(() => none.sent().length);
    assert.ok(!("issue_type" in none.sent()[0].metadata));
  });
});

describe("submitting", () => {
  it("validates before sending: message required, email shape, with accessible errors", () => {
    const { q, type, submit, sent, fetch } = mount({ fields: { email: "required" } });
    submit();
    assert.equal(sent().length, 0);
    assert.equal(fetch.calls.length, 0, "nothing at all goes over the network");
    const message = q("textarea");
    assert.equal(message.getAttribute("aria-invalid"), "true");
    assert.match(q("[id$='-message-err']").textContent, /fill this in/i);
    assert.equal(message.getAttribute("aria-describedby"), q("[id$='-message-err']").id);
    assert.equal(q("[id$='-email-err']").hidden, false);

    type("textarea", "hi");
    type("input[name=email]", "not-an-email");
    submit();
    assert.match(q("[id$='-email-err']").textContent, /valid email/i);
    assert.equal(sent().length, 0);
    assert.equal(message.hasAttribute("aria-invalid"), false); // cleared once fixed
  });

  it("sends everything the form collected, in the shape the API takes", async () => {
    const { all, type, submit, sent, q } = mount({
      fields: { rating: true, name: "optional", email: "optional" },
      metadata: () => ({ route: "/pricing", plan: "pro" }),
      pageUrl: "https://app.example.com/custom",
    });
    all(".type")[2].click();
    all(".star")[3].click();
    type("textarea", "  How do I export?  ");
    type("input[name=name]", "Ada");
    type("input[name=email]", "ada@example.com");
    submit();
    await until(() => sent().length);
    assert.deepEqual(sent()[0], {
      message: "How do I export?", rating: 4, name: "Ada", email: "ada@example.com",
      page_url: "https://app.example.com/custom",
      metadata: { widget_version: g.VERSION, issue_type: "question", route: "/pricing", plan: "pro" }, website: "",
    });
    assert.equal(q("form").hidden, true);
    assert.equal(q(".done").hidden, false);
    assert.match(q(".done").textContent, /Thank you/);
  });

  it("reports the page URL by default", async () => {
    const { type, submit, sent } = mount();
    type("textarea", "hi");
    submit();
    await until(() => sent().length);
    assert.equal(sent()[0].page_url, "https://app.example.com/pricing?x=1");
  });

  it("has an off-screen, hidden-from-assistive-tech honeypot and passes its value through", async () => {
    const { q, type, submit, sent } = mount();
    const trap = q("input[name=website]");
    assert.equal(trap.closest(".honeypot").getAttribute("aria-hidden"), "true");
    assert.equal(trap.tabIndex, -1);
    assert.equal(trap.getAttribute("autocomplete"), "off");
    type("textarea", "hi");
    submit();
    await until(() => sent().length);
    assert.equal(sent()[0].website, "");

    trap.value = "http://spam.example";
    q("form").hidden = false;
    type("textarea", "again");
    submit();
    await until(() => sent().length > 1);
    assert.equal(sent()[1].website, "http://spam.example");
  });

  it("shows sending state, blocks double submits, then thanks and emits submit", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { w, q, type, submit, fetch } = mount({}, async () => { await gate; return ok(); });
    const events = [];
    w.on("submit", (d) => events.push(d));
    type("textarea", "hi");
    submit();
    submit();
    await until(() => fetch.calls.some((c) => c.url.endsWith("/feedback")));
    assert.equal(q(".submit").disabled, true);
    assert.equal(q(".submit").textContent, "Sending…");
    assert.equal(q("form").getAttribute("aria-busy"), "true");
    release();
    await until(() => events.length);
    assert.equal(fetch.calls.filter((c) => c.url.endsWith("/feedback")).length, 1);
    assert.equal(events[0].id, "11111111-1111-1111-1111-111111111111");
    assert.equal(events[0].payload.message, "hi");
  });

  it("closes itself after the configured delay and starts fresh next time", async () => {
    const { w, q, all, type, submit, sent } = mount({ closeDelay: 30 });
    w.open();
    all(".type")[0].click();
    type("textarea", "hi");
    submit();
    await until(() => sent().length);
    await until(() => !w.isOpen);
    w.open();
    assert.equal(q("form").hidden, false);
    assert.equal(q("textarea").value, "");
    assert.ok(all(".type").every((r) => r.getAttribute("aria-checked") === "false"));
  });

  it("explains failures and lets the visitor try again", async () => {
    const outcomes = [
      { status: 429, headers: { "Retry-After": "30" }, body: {} },
      { status: 403, body: { detail: "Forbidden" } },
      ok(),
    ];
    const { w, q, type, submit, sent } = mount({}, () => outcomes.shift());
    const errors = [];
    w.on("error", (d) => errors.push(d));
    type("textarea", "hi");
    submit();
    await until(() => errors.length === 1);
    assert.match(q(".status").textContent, /try again in 30 seconds/);
    assert.equal(q(".status").getAttribute("data-kind"), "error");
    assert.equal(q(".submit").disabled, false);
    assert.equal(q("textarea").value, "hi", "what they typed is kept");
    submit();
    await until(() => errors.length === 2);
    assert.match(q(".status").textContent, /couldn't send/);
    submit();
    await until(() => q(".done").hidden === false);
    assert.equal(sent().length, 3);
    assert.deepEqual(errors.map((e) => e.reason), ["rate_limited", "rejected"]);
  });

  it("maps server-side validation messages onto the fields", async () => {
    const { q, type, submit } = mount({}, () => ({ status: 422, body: { detail: [{ loc: ["body", "email"], msg: "value is not a valid email address" }] } }));
    type("textarea", "hi");
    submit();
    await until(() => !q("[id$='-email-err']").hidden);
    assert.equal(q("[id$='-email-err']").textContent, "value is not a valid email address");
    assert.equal(q("input[name=email]").getAttribute("aria-invalid"), "true");
  });

  it("says so when the network is down", async () => {
    const { q, type, submit } = mount({}, () => { throw new TypeError("Failed to fetch"); });
    type("textarea", "hi");
    submit();
    await until(() => q(".status").textContent);
    assert.match(q(".status").textContent, /couldn't reach the server/);
  });

  it("lets the page veto or change the payload, and survives broken page callbacks", async () => {
    const vetoed = mount({ beforeSubmit: () => false });
    vetoed.type("textarea", "hi");
    vetoed.submit();
    await wait(30);
    assert.equal(vetoed.sent().length, 0);

    const changed = mount({ beforeSubmit: async (p) => ({ ...p, message: p.message + " [vip]", metadata: { ...p.metadata, vip: true } }) });
    changed.type("textarea", "hi");
    changed.submit();
    await until(() => changed.sent().length);
    assert.equal(changed.sent()[0].message, "hi [vip]");
    assert.equal(changed.sent()[0].metadata.vip, true);

    const errors = [];
    const origError = console.error;
    console.error = (...a) => errors.push(a.join(" "));
    try {
      const broken = mount({ metadata: () => { throw new Error("boom"); } });
      broken.w.on("submit", () => { throw new Error("listener boom"); });
      broken.type("textarea", "hi");
      broken.submit();
      await until(() => broken.sent().length);
      await until(() => broken.q(".done").hidden === false);
      assert.deepEqual(Object.keys(broken.sent()[0].metadata).sort(), ["widget_version"]);
      assert.ok(errors.some((e) => /metadata function threw/.test(e)) && errors.some((e) => /listener threw/.test(e)));
    } finally {
      console.error = origError;
    }
  });

  it("solves the site's bot-protection challenge before sending", async () => {
    const fetch = mockFetch((call) => (call.url.endsWith("/challenge")
      ? { status: 200, body: { mode: "pow", algorithm: "sha256", token: "tok.sig", bits: 8 } } : ok()));
    globalThis.fetch = fetch;
    const w = g.createWidget({ url: URL_, key: "pk_test", closeDelay: 0 });
    widgets.push(w);
    w.element.shadowRoot.querySelector("textarea").value = "hi";
    w.element.shadowRoot.querySelector("form").dispatchEvent(new window.Event("submit", { cancelable: true }));
    await until(() => fetch.calls.length === 2);
    assert.match(fetch.calls[1].body.challenge, /^tok\.sig:\d+$/);
  });
});

describe("fields and customisation", () => {
  it("hides optional fields by default (just message and email) and honours the field modes", () => {
    const defaults = mount();
    assert.deepEqual(defaults.all("input:not([name=website]), textarea, select").map((e) => e.name), ["message", "email"]);
    const full = mount({ fields: { rating: true, name: "required", email: false } });
    assert.equal(full.q("input[name=email]"), null);
    assert.ok(full.q("input[name=name]") && full.all(".star").length === 5);
  });

  it("collects extra fields into metadata and enforces required ones", async () => {
    const { q, all, type, submit, sent } = mount({
      extraFields: [
        { id: "plan", label: "Plan", type: "select", options: ["free", "pro"], required: true },
        { id: "contact_ok", label: "You may contact me", type: "checkbox" },
        { id: "steps", label: "Steps", type: "textarea", maxLength: 100 },
        { id: "order", label: "Order number" },
      ],
    });
    type("textarea[name=message]", "hi");
    submit();
    assert.equal(sent().length, 0);
    assert.match(q("[id$='-x-plan-err']").textContent, /fill this in/i);

    q("select[name=plan]").value = "pro";
    q("input[name=contact_ok]").checked = true;
    type("input[name=order]", " A-1001 ");
    submit();
    await until(() => sent().length);
    assert.deepEqual(sent()[0].metadata, { widget_version: g.VERSION, plan: "pro", contact_ok: true, order: "A-1001" });
    assert.equal(all("[data-extra]").length, 4);
  });

  it("applies theme, colors, radius and strings, and re-applies them on update()", () => {
    const { w, q } = mount({ theme: "dark", colors: { accent: "#ff0066" }, radius: 4, zIndex: 99, strings: { title: "Tell us", launcher: "Help" } });
    assert.equal(w.element.getAttribute("data-theme"), "dark");
    assert.equal(w.element.style.getPropertyValue("--gm-accent"), "#ff0066");
    assert.equal(w.element.style.getPropertyValue("--gm-radius"), "4px");
    assert.equal(w.element.style.getPropertyValue("--gm-z"), "99");
    assert.equal(q("h2").textContent, "Tell us");
    assert.equal(q(".launcher").textContent.trim(), "Help");

    w.update({ theme: "light", colors: { accent: "#00aa55" }, strings: { title: "Hello" } });
    assert.equal(w.element.getAttribute("data-theme"), "light");
    assert.equal(w.element.style.getPropertyValue("--gm-accent"), "#00aa55");
    assert.equal(w.element.shadowRoot.querySelector("h2").textContent, "Hello");
  });

  it("keeps a closed widget closed across update() and an open one open", () => {
    const { w } = mount();
    w.update({ position: "bottom-left" });
    assert.equal(w.isOpen, false);
    w.open();
    w.update({ position: "bottom-right" });
    assert.equal(w.element.shadowRoot.querySelector(".panel").hidden, false);
  });

  it("styles itself inside its shadow root and only ever sets custom properties through the CSSOM", () => {
    const { root, w } = mount();
    assert.ok(root.querySelector("style")?.textContent.includes(":host"), "jsdom has no constructable sheets, so the <style> fallback is used");
    // jsdom mirrors CSSOM writes into a style attribute; real browsers allow those under a strict CSP
    // (checked in the browser run). What matters is that nothing but --gm-* properties is ever set.
    for (const el of root.querySelectorAll("[style]")) assert.match(el.getAttribute("style"), /^(--gm-[a-z-]+: [^;]+;\s*)+$/);
    assert.equal(w.element.shadowRoot.mode, "open");
  });

  it("reports what it supports", () => {
    const { w } = mount();
    assert.equal(w.supports("issue-types"), true);
    assert.equal(w.supports("screenshots"), false);
  });
});

describe("inline mode", () => {
  it("renders the form inside the target, without launcher or close button", () => {
    const { w, q } = mount({ mode: "inline", target: "#slot" });
    assert.equal(w.element.parentElement.id, "slot");
    assert.equal(q(".launcher"), null);
    assert.equal(q(".close"), null);
    assert.equal(q(".panel").hidden, false);
    assert.equal(q(".panel").getAttribute("role"), "group");
  });

  it("accepts an element as target and offers 'send more' after a submission", async () => {
    const slot = document.getElementById("slot");
    const { q, type, submit, sent } = mount({ mode: "inline", target: slot });
    type("textarea", "hi");
    submit();
    await until(() => sent().length);
    await until(() => !q(".done").hidden);
    q(".again").click();
    assert.equal(q("form").hidden, false);
    assert.equal(q("textarea").value, "");
  });

  it("fails clearly when the target is missing", () => {
    assert.throws(() => g.createWidget({ url: URL_, key: "pk", mode: "inline", target: "#nope" }), /was not found/);
  });
});

describe("mounting", () => {
  it("waits for the document when loaded early", async () => {
    const dom = setupDom();
    Object.defineProperty(dom.window.document, "readyState", { value: "loading", configurable: true });
    const w = g.createWidget({ url: URL_, key: "pk_test" });
    widgets.push(w);
    assert.equal(w.element.isConnected, false);
    dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
    assert.equal(w.element.isConnected, true);
  });

  it("warns about unknown options but still works", () => {
    const warnings = captureWarnings();
    try {
      const { w } = mount({ somethingNew: 1 });
      assert.ok(w.element.isConnected);
      assert.ok(warnings.seen.some((m) => /unknown option "somethingNew"/.test(m)));
    } finally {
      warnings.restore();
    }
  });
});

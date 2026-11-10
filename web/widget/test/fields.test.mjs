import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { BUNDLE, mockFetch, ok, setupDom, teardownDom, until, wait } from "./helpers.mjs";

const g = await import(BUNDLE.href);
const URL_ = "https://feedback.example.com/v1/api";

const PLAN = {
  id: "plan", type: "select", label: "Plan", required: false, max_length: null,
  options: [{ value: "free", label: "Free" }, { value: "pro", label: "Pro" }],
  translations: {
    de: { label: "Tarif", options: { free: "Kostenlos" } },
    pt: { label: "Plano", options: {} },
  },
};
const BETA = { id: "beta", type: "checkbox", label: "Beta tester", required: false, options: [], max_length: null, translations: {} };
const COMPANY = { id: "company", type: "text", label: "Company", required: false, options: [], max_length: 12, translations: {} };
const config = (fields = [PLAN, BETA, COMPANY], extra = {}) => ({ status: 200, body: { fields, attachments: { enabled: false }, ...extra } });

let widgets = [];
let originalFetch;

function mount(options = {}, { cfg = config(), handler = () => ok() } = {}) {
  const fetch = mockFetch((call) => {
    if (call.url.endsWith("/challenge")) return { status: 200, body: { mode: "off" } };
    if (call.url.endsWith("/feedback/config")) return typeof cfg === "function" ? cfg() : cfg;
    return handler(call);
  });
  globalThis.fetch = fetch;
  const w = g.createWidget({ url: URL_, key: "pk_test", closeDelay: 0, ...options });
  widgets.push(w);
  const root = w.element.shadowRoot;
  const q = (sel) => root.querySelector(sel);
  const all = (sel) => [...root.querySelectorAll(sel)];
  const submissions = () => fetch.calls.filter((c) => /\/feedback$/.test(c.url));
  const submit = () => q("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  const write = (text) => { q("textarea").value = text; };
  const set = (id, value) => {
    const el = q(`[data-extra="${id}"]`);
    if (el.type === "checkbox") el.checked = value;
    else el.value = value;
  };
  const label = (id) => q(`label[for$="-x-${id}"]`)?.textContent.replace(/\s*\(.*\)\s*$/, "").trim();
  return { w, root, q, all, fetch, submissions, submit, write, set, label };
}

async function opened(ui) {
  ui.w.open();
  await until(() => ui.q("[data-extra]"));
  return ui;
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

describe("the site's custom fields", () => {
  it("appear once the site's config arrives, in the site's order", async () => {
    const ui = await opened(mount({ locale: "en" }));
    assert.deepEqual(ui.all("[data-extra]").map((e) => e.dataset.extra), ["plan", "beta", "company"]);
    assert.equal(ui.q('[data-extra="plan"]').tagName, "SELECT");
    assert.deepEqual([...ui.q('[data-extra="plan"]').options].map((o) => [o.value, o.textContent]), [["", ""], ["free", "Free"], ["pro", "Pro"]]);
    assert.equal(ui.q('[data-extra="beta"]').type, "checkbox");
    assert.equal(ui.q('[data-extra="company"]').getAttribute("maxlength"), "12");
  });

  it("are sent under their id, with the stored value of a choice and not its label", async () => {
    const ui = await opened(mount({ locale: "de" }));
    ui.write("hello");
    ui.set("plan", "free"); // shown to this visitor as "Kostenlos"
    ui.set("beta", true);
    ui.set("company", "  Acme  ");
    ui.submit();
    await until(() => ui.submissions().length === 1);
    const { metadata } = ui.submissions()[0].body;
    assert.equal(metadata.plan, "free");
    assert.equal(metadata.beta, true);
    assert.equal(metadata.company, "Acme");
  });

  it("need no site fields: a site without any renders the form as before", async () => {
    const ui = mount({}, { cfg: config([]) });
    ui.w.open();
    await wait(40);
    assert.equal(ui.all("[data-extra]").length, 0);
  });

  it("ignore entries this widget cannot draw, and a failed config", async () => {
    const odd = [{ id: "n", type: "number", label: "N" }, { id: "Bad Id", type: "text", label: "x" }, { id: "s", type: "select", label: "S", options: [] }, 7, null, COMPANY];
    const ui = await opened(mount({}, { cfg: config(odd) }));
    assert.deepEqual(ui.all("[data-extra]").map((e) => e.dataset.extra), ["company"]);

    const down = mount({ extraFields: [{ id: "page", label: "From the page" }] }, { cfg: { status: 500, body: {} } });
    down.w.open();
    await wait(40);
    assert.deepEqual(down.all("[data-extra]").map((e) => e.dataset.extra), ["page"], "the page's own fields still work");
  });
});

describe("languages", () => {
  const labelsFor = async (locale) => {
    const ui = await opened(mount({ locale }));
    return { plan: ui.label("plan"), options: [...ui.q('[data-extra="plan"]').options].map((o) => o.textContent) };
  };

  it("show the translation that matches, falling back to the site's own text", async () => {
    assert.deepEqual(await labelsFor("de"), { plan: "Tarif", options: ["", "Kostenlos", "Pro"] }); // Pro is untranslated
    assert.deepEqual(await labelsFor("fr"), { plan: "Plan", options: ["", "Free", "Pro"] });
  });

  it("match on the language when the region has no translation of its own, in any case", async () => {
    assert.equal((await labelsFor("de-AT")).plan, "Tarif");
    assert.equal((await labelsFor("DE_ch")).plan, "Tarif");
    assert.equal((await labelsFor("pt-BR")).plan, "Plano");
  });

  it("default to the page's language", async () => {
    document.documentElement.lang = "de";
    assert.equal((await labelsFor(undefined)).plan, "Tarif");
  });

  it("change with update({ locale })", async () => {
    const ui = await opened(mount({ locale: "en" }));
    assert.equal(ui.label("plan"), "Plan");
    ui.w.update({ locale: "de" });
    assert.equal(ui.label("plan"), "Tarif");
  });
});

describe("required fields", () => {
  const required = config([{ ...PLAN, required: true }, { ...BETA, required: true }]);

  it("stop the submission and say which are missing", async () => {
    const ui = await opened(mount({ locale: "en" }, { cfg: required }));
    ui.write("hello");
    ui.submit();
    await wait(30);
    assert.equal(ui.submissions().length, 0);
    assert.equal(ui.q(`[id$="-x-plan-err"]`).hidden, false);
    assert.equal(ui.q(`[id$="-x-beta-err"]`).hidden, false);
    ui.set("plan", "pro");
    ui.set("beta", true);
    ui.submit();
    await until(() => ui.submissions().length === 1);
  });

  it("are asked for even if the visitor submits before the config has arrived", async () => {
    let release;
    const slow = new Promise((r) => (release = r));
    const ui = mount({ locale: "en" }, { cfg: () => slow.then(() => required) });
    ui.w.open();
    ui.write("hello");
    ui.submit(); // the fields are not on the form yet
    await wait(20);
    assert.equal(ui.submissions().length, 0, "waits for the site's questions");
    release();
    await until(() => ui.q("[data-extra]"));
    await wait(20);
    assert.equal(ui.submissions().length, 0, "and then finds them unanswered");
    assert.equal(ui.q(`[id$="-x-plan-err"]`).hidden, false);
  });

  it("show the server's refusal on the field, in the widget's own words", async () => {
    const refuse = () => ({ status: 422, body: { detail: [{ loc: ["body", "metadata", "plan"], msg: "This field is required" }] } });
    const ui = await opened(mount({ locale: "en", strings: { required: "Pflichtfeld" } }, { cfg: config(), handler: refuse }));
    ui.write("hello");
    ui.submit();
    await until(() => ui.submissions().length === 1);
    await until(() => !ui.q(`[id$="-x-plan-err"]`).hidden);
    assert.equal(ui.q(`[id$="-x-plan-err"]`).textContent, "Pflichtfeld");
  });
});

describe("fields from the page", () => {
  it("step aside for a site field with the same id", async () => {
    const ui = mount({ locale: "en", extraFields: [{ id: "plan", label: "Page plan", type: "text" }, { id: "page", label: "From the page" }] });
    ui.w.open();
    await until(() => ui.q('[data-extra="plan"]')?.tagName === "SELECT"); // the page's own input shows until the config lands
    assert.equal(ui.all('[data-extra="plan"]').length, 1);
    assert.equal(ui.q('[data-extra="plan"]').tagName, "SELECT", "the site's definition wins");
    assert.equal(ui.all('[data-extra="page"]').length, 1);
    ui.write("hello");
    ui.set("plan", "pro");
    ui.set("page", "x");
    ui.submit();
    await until(() => ui.submissions().length === 1);
    assert.deepEqual([ui.submissions()[0].body.metadata.plan, ui.submissions()[0].body.metadata.page], ["pro", "x"]);
  });
});

describe("the metadata limit", () => {
  const many = Object.fromEntries(Array.from({ length: 12 }, (_, i) => [`k${i}`, i]));

  it("follows what the server says, keeping the widget's own keys", async () => {
    const ui = await opened(mount({ metadata: many }, { cfg: config([PLAN], { metadata_max_keys: 6 }) }));
    ui.write("hello");
    ui.submit();
    await until(() => ui.submissions().length === 1);
    const keys = Object.keys(ui.submissions()[0].body.metadata);
    assert.equal(keys.length, 6);
    assert.equal(keys[0], "widget_version");
  });

  it("stays at 20 against a server that does not say", async () => {
    const ui = await opened(mount({ metadata: many }, { cfg: { status: 200, body: { fields: [PLAN] } } }));
    ui.write("hello");
    ui.submit();
    await until(() => ui.submissions().length === 1);
    assert.equal(Object.keys(ui.submissions()[0].body.metadata).length, 13); // widget_version + the 12 given
  });

  it("is a number the client reports, and a limit too small to hold the widget's keys is ignored", async () => {
    const client = g.createClient({ url: URL_, key: "pk_test", fetch: mockFetch(() => config([], { metadata_max_keys: 50 })) });
    assert.equal((await client.config()).maxMetadataKeys, 50);
    const odd = g.createClient({ url: URL_, key: "pk_test", fetch: mockFetch(() => config([], { metadata_max_keys: 1 })) });
    assert.equal((await odd.config()).maxMetadataKeys, null);
  });
});

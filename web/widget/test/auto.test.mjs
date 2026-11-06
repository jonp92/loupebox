import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { BUNDLE, captureWarnings, mockFetch, setupDom, teardownDom, until, wait } from "./helpers.mjs";

let n = 0;
let originalFetch;
let calls;

beforeEach(() => {
  globalThis.window = setupDom().window;
  originalFetch = globalThis.fetch;
  const fetch = mockFetch(() => ({ status: 200, body: { attachments: { enabled: false } } }));
  globalThis.fetch = fetch;
  calls = fetch.calls;
});
afterEach(() => {
  document.querySelectorAll("loupebox-widget").forEach((w) => w.remove());
  globalThis.fetch = originalFetch;
  teardownDom();
  delete globalThis.window;
});

/** Put a script tag on the page, then load the bundle the way the browser does (each import re-runs it). */
async function load(attrs = {}, src = BUNDLE.href) {
  const s = document.createElement("script");
  s.type = "module";
  s.src = src;
  for (const [k, v] of Object.entries(attrs)) s.setAttribute(`data-${k}`, v);
  document.body.append(s);
  await import(`${BUNDLE.href}?auto=${++n}`);
}
const widgets = () => [...document.querySelectorAll("loupebox-widget")];
const API = "https://feedback.example.com/v1/api";

describe("starting from the script tag", () => {
  it("does nothing without a key", async () => {
    await load({});
    assert.equal(widgets().length, 0);
  });

  it("mounts a floating widget for a tag with a key and a url", async () => {
    await load({ key: "pk_x", url: API });
    const [w] = widgets();
    assert.ok(w, "a widget is on the page");
    assert.equal(w.shadowRoot.querySelector(".launcher") !== null, true);
    w.shadowRoot.querySelector(".launcher").click();
    await until(() => calls.some((c) => c.url === `${API}/feedback/config`));
    assert.equal(calls[0].init.headers["X-API-Key"], "pk_x");
  });

  it("exposes the controller for the page's own button, and announces it", async () => {
    let heard;
    window.addEventListener("loupebox:ready", (e) => (heard = e.detail));
    await load({ key: "pk_x", url: API, launcher: "false" });
    assert.ok(window.loupebox && typeof window.loupebox.open === "function");
    assert.equal(heard, window.loupebox);
    assert.equal(widgets()[0].shadowRoot.querySelector(".launcher"), null);
    window.loupebox.open();
    assert.equal(window.loupebox.isOpen, true);
    delete window.loupebox;
  });

  it("reads the other attributes as options", async () => {
    await load({
      key: "pk_x", url: API, position: "bottom-left", theme: "dark", rating: "true", name: "required",
      email: "false", "require-issue-type": "true", "close-delay": "0", radius: "4", images: "false",
    });
    const w = widgets()[0];
    assert.equal(w.getAttribute("data-theme"), "dark");
    const root = w.shadowRoot;
    assert.equal(root.querySelector("[data-position]").getAttribute("data-position"), "bottom-left");
    assert.ok(root.querySelector(".rating"), "rating asked for");
    assert.ok(root.querySelector('input[name="name"]'), "name shown");
    assert.equal(root.querySelector('input[name="email"]'), null, "email turned off");
    root.querySelector(".launcher").click();
    await wait(30);
    assert.equal(calls.length, 0, "data-images=false never asks the site about images");
  });

  it("renders inline into a target", async () => {
    document.getElementById("slot").id = "here";
    await load({ key: "pk_x", url: API, mode: "inline", target: "#here" });
    assert.equal(document.querySelector("#here loupebox-widget") !== null, true);
    assert.equal(widgets()[0].shadowRoot.querySelector(".launcher"), null);
  });

  it("leaves tags for other scripts alone", async () => {
    await load({ key: "pk_x", url: API }, "https://other.example.com/analytics.js");
    assert.equal(widgets().length, 0);
  });

  it("matches the tag whatever its query string", async () => {
    await load({ key: "pk_x", url: API }, `${BUNDLE.href}?v=7`);
    assert.equal(widgets().length, 1);
  });

  it("starts one widget per tag, once", async () => {
    await load({ key: "pk_a", url: API });
    await import(`${BUNDLE.href}?auto=again`); // the tag was already started
    assert.equal(widgets().length, 1);
  });

  it("does not break the page when an attribute is bad", async () => {
    const quiet = captureWarnings();
    const original = console.error;
    const errors = [];
    console.error = (...a) => errors.push(a.join(" "));
    try {
      await load({ key: "pk_x" }); // no data-url, and a file: script has no origin to derive one from
    } finally {
      console.error = original;
      quiet.restore();
    }
    assert.equal(widgets().length, 0);
    assert.match(errors.join("\n"), /could not start from the script tag/);
  });
});

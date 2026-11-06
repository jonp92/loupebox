import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { BUNDLE, mockFetch, ok, setupDom, teardownDom, until, wait } from "./helpers.mjs";

const g = await import(BUNDLE.href);
const URL_ = "https://feedback.example.com/v1/api";
const OFF = { status: 200, body: { mode: "off" } };
const ON = { attachments: { enabled: true, max_count: 3, max_bytes: 1000, max_edge: 2048 } };

let widgets = [];
let originalFetch;

/** A widget with a mocked network. `config` answers GET /feedback/config, `handler` the submissions. */
function mount(options = {}, { config = { status: 200, body: ON }, handler = () => ok() } = {}) {
  const fetch = mockFetch((call) => {
    if (call.url.endsWith("/challenge")) return OFF;
    if (call.url.endsWith("/feedback/config")) return config;
    return handler(call);
  });
  globalThis.fetch = fetch;
  const w = g.createWidget({ url: URL_, key: "pk_test", closeDelay: 0, ...options });
  widgets.push(w);
  const root = w.element.shadowRoot;
  const q = (sel) => root.querySelector(sel);
  const all = (sel) => [...root.querySelectorAll(sel)];
  const configCalls = () => fetch.calls.filter((c) => c.url.endsWith("/feedback/config"));
  const submissions = () => fetch.calls.filter((c) => /\/feedback(\/with-images)?$/.test(c.url));
  const submit = () => q("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  const write = (text) => {
    q("textarea").value = text;
  };
  return { w, root, q, all, fetch, configCalls, submissions, submit, write };
}

const png = (name = "shot.png", size = 50) => new File([new Uint8Array(size)], name, { type: "image/png" });

/** Choose files the way the file dialog does. */
function choose(ui, ...files) {
  const input = ui.q('input[type="file"]');
  Object.defineProperty(input, "files", { value: files, configurable: true });
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
}

function event(type, props) {
  const e = new window.Event(type, { bubbles: true, cancelable: true });
  for (const [k, v] of Object.entries(props)) Object.defineProperty(e, k, { value: v });
  return e;
}

/** Open a floating widget and wait for the image control to appear (or the config answer to land). */
async function opened(ui, expectControl = true) {
  ui.w.open();
  await until(() => ui.configCalls().length === 1);
  if (expectControl) await until(() => !ui.q(".images").hidden);
  else await wait(20);
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

describe("asking the site what it accepts", () => {
  it("asks once, on first open, with the key and no body", async () => {
    const ui = mount();
    assert.equal(ui.configCalls().length, 0, "nothing is requested before the visitor opens the widget");
    await opened(ui);
    ui.w.close();
    ui.w.open();
    const [call] = ui.configCalls();
    assert.equal(call.init.method, "GET");
    assert.equal(call.init.headers["X-API-Key"], "pk_test");
    assert.equal(call.init.body, undefined);
    assert.equal(call.init.credentials, "omit");
    assert.equal(ui.configCalls().length, 1);
  });

  it("shows no control when the site does not accept images", async () => {
    const ui = await opened(mount({}, { config: { status: 200, body: { attachments: { enabled: false } } } }), false);
    assert.equal(ui.q(".images").hidden, true);
    assert.equal(ui.q(".add-image"), null);
  });

  it("works as before against a server that has never heard of images", async () => {
    const ui = await opened(mount({}, { config: { status: 404, body: { detail: "Not Found" } } }), false);
    assert.equal(ui.q(".add-image"), null);
    ui.write("hello");
    ui.submit();
    await until(() => ui.submissions().length === 1);
    assert.ok(ui.submissions()[0].url.endsWith("/feedback"));
    assert.equal(ui.submissions()[0].body.message, "hello");
  });

  it("never asks when the page turned images off", async () => {
    const ui = mount({ images: false });
    ui.w.open();
    await wait(30);
    assert.equal(ui.configCalls().length, 0);
    assert.equal(ui.q(".add-image"), null);
  });

  it("asks at once in inline mode and keeps typed text when the answer arrives", async () => {
    const ui = mount({ mode: "inline", target: "#slot" });
    ui.write("typed before the answer");
    await until(() => !ui.q(".images").hidden);
    assert.equal(ui.q("textarea").value, "typed before the answer");
  });

  it("asks again after update() points at another site", async () => {
    const ui = await opened(mount());
    ui.w.update({ key: "pk_other" });
    await until(() => ui.configCalls().length === 2);
    assert.equal(ui.configCalls()[1].init.headers["X-API-Key"], "pk_other");
  });
});

describe("adding images", () => {
  it("offers a labelled button and hint", async () => {
    const ui = await opened(mount());
    const button = ui.q(".add-image");
    assert.equal(button.textContent.trim(), "Add image");
    assert.equal(button.type, "button");
    assert.equal(ui.root.getElementById(button.getAttribute("aria-describedby")).textContent, "You can also paste or drop an image.");
    assert.equal(ui.q('input[type="file"]').accept, "image/png,image/jpeg,image/webp");
    assert.equal(ui.q('input[type="file"]').multiple, true);
  });

  it("shows a thumbnail with a remove button and a count", async () => {
    const ui = await opened(mount());
    choose(ui, png("a.png"), png("b.png"));
    await until(() => ui.all(".thumbs li").length === 2);
    assert.equal(ui.q(".image-row .hint").textContent, "2 of 3 images");
    assert.deepEqual(ui.all(".remove").map((b) => b.getAttribute("aria-label")), ["Remove image 1", "Remove image 2"]);
    assert.equal(ui.q(".thumbs").getAttribute("aria-label"), "Attached images");
    ui.all(".remove")[0].click();
    assert.equal(ui.all(".thumbs li").length, 1);
    assert.equal(ui.q(".image-row .hint").textContent, "1 of 3 images");
  });

  it("takes pasted images and leaves pasted text alone", async () => {
    const ui = await opened(mount());
    const text = event("paste", { clipboardData: { files: [] } });
    ui.q("textarea").dispatchEvent(text);
    assert.equal(text.defaultPrevented, false, "a text paste is the browser's");
    const pic = event("paste", { clipboardData: { files: [png()] } });
    ui.q("textarea").dispatchEvent(pic);
    assert.equal(pic.defaultPrevented, true);
    await until(() => ui.all(".thumbs li").length === 1);
  });

  it("takes dropped images, with a visible drop state", async () => {
    const ui = await opened(mount());
    const over = event("dragover", { dataTransfer: { types: ["Files"], files: [] } });
    ui.q(".panel").dispatchEvent(over);
    assert.equal(over.defaultPrevented, true);
    assert.equal(ui.q(".panel").getAttribute("data-dragging"), "true");
    ui.q(".panel").dispatchEvent(event("dragleave", { relatedTarget: null }));
    assert.equal(ui.q(".panel").hasAttribute("data-dragging"), false);
    const drop = event("drop", { dataTransfer: { types: ["Files"], files: [png("dropped.png")] } });
    ui.q(".panel").dispatchEvent(drop);
    assert.equal(drop.defaultPrevented, true);
    await until(() => ui.all(".thumbs li").length === 1);
    assert.equal(ui.q(".panel").hasAttribute("data-dragging"), false);
  });

  it("ignores drags that carry no files", async () => {
    const ui = await opened(mount());
    const over = event("dragover", { dataTransfer: { types: ["text/plain"], files: [] } });
    ui.q(".panel").dispatchEvent(over);
    assert.equal(over.defaultPrevented, false);
    assert.equal(ui.q(".panel").hasAttribute("data-dragging"), false);
  });

  it("does not take over paste or drop when the site accepts no images", async () => {
    const ui = await opened(mount({}, { config: { status: 200, body: { attachments: { enabled: false } } } }), false);
    const pic = event("paste", { clipboardData: { files: [png()] } });
    ui.q("textarea").dispatchEvent(pic);
    assert.equal(pic.defaultPrevented, false);
    const drop = event("drop", { dataTransfer: { types: ["Files"], files: [png()] } });
    ui.q(".panel").dispatchEvent(drop);
    assert.equal(drop.defaultPrevented, false);
  });

  it("refuses other file types, with a message next to the control", async () => {
    const ui = await opened(mount());
    choose(ui, new File(["<svg/>"], "x.svg", { type: "image/svg+xml" }), new File(["hi"], "a.txt", { type: "text/plain" }));
    await until(() => !ui.q('[id$="-images-err"]').hidden);
    assert.equal(ui.q('[id$="-images-err"]').textContent, "Only PNG, JPEG and WebP images can be attached.");
    assert.equal(ui.all(".thumbs li").length, 0);
  });

  it("stops at the site's limit", async () => {
    const ui = await opened(mount());
    choose(ui, png("1.png"), png("2.png"), png("3.png"), png("4.png"));
    await until(() => !ui.q('[id$="-images-err"]').hidden);
    assert.equal(ui.all(".thumbs li").length, 3);
    assert.equal(ui.q('[id$="-images-err"]').textContent, "You can attach up to 3 images.");
    assert.equal(ui.q(".add-image").disabled, true);
    ui.all(".remove")[0].click();
    assert.equal(ui.q(".add-image").disabled, false);
    assert.equal(ui.q('[id$="-images-err"]').hidden, true, "removing one clears the message");
  });

  it("refuses a file over the byte limit that cannot be made smaller", async () => {
    const ui = await opened(mount());
    choose(ui, png("big.png", 5000));
    await until(() => !ui.q('[id$="-images-err"]').hidden);
    assert.match(ui.q('[id$="-images-err"]').textContent, /too large/);
    assert.equal(ui.all(".thumbs li").length, 0);
  });

  it("uses the visitor's own strings", async () => {
    const ui = mount({ strings: { addImage: "Bild hinzufügen", imageCount: "{count}/{max}", removeImage: "Bild {n} entfernen" } });
    await opened(ui);
    assert.equal(ui.q(".add-image").textContent.trim(), "Bild hinzufügen");
    choose(ui, png());
    await until(() => ui.all(".thumbs li").length === 1);
    assert.equal(ui.q(".image-row .hint").textContent, "1/3");
    assert.equal(ui.q(".remove").getAttribute("aria-label"), "Bild 1 entfernen");
  });
});

describe("sending", () => {
  it("sends one multipart request with the usual JSON and the images", async () => {
    const ui = await opened(mount());
    ui.write("see this");
    choose(ui, png("one.png"), png("two.png"));
    await until(() => ui.all(".thumbs li").length === 2);
    ui.submit();
    await until(() => ui.submissions().length === 1);
    const [call] = ui.submissions();
    assert.ok(call.url.endsWith("/feedback/with-images"));
    assert.ok(call.form instanceof FormData);
    assert.equal(call.init.headers["Content-Type"], undefined, "the browser sets the multipart boundary");
    assert.equal(call.init.headers["X-API-Key"], "pk_test");
    const payload = JSON.parse(call.form.get("payload"));
    assert.equal(payload.message, "see this");
    assert.equal(payload.metadata.widget_version, g.VERSION);
    assert.deepEqual(call.form.getAll("images").map((f) => [f.name, f.type, f.size]), [["one.png", "image/png", 50], ["two.png", "image/png", 50]]);
  });

  it("sends plain JSON when no image was added, even on a site that accepts them", async () => {
    const ui = await opened(mount());
    ui.write("no picture");
    ui.submit();
    await until(() => ui.submissions().length === 1);
    const [call] = ui.submissions();
    assert.ok(call.url.endsWith("/feedback") && !call.url.includes("with-images"));
    assert.equal(call.init.headers["Content-Type"], "application/json");
    assert.equal(call.body.message, "no picture");
  });

  it("clears the images after a successful send, and offers none the next time", async () => {
    const ui = await opened(mount());
    ui.write("sent");
    choose(ui, png());
    await until(() => ui.all(".thumbs li").length === 1);
    const revoked = [];
    const original = URL.revokeObjectURL;
    URL.revokeObjectURL = (u) => revoked.push(u);
    try {
      ui.submit();
      await until(() => !ui.q(".done").hidden);
    } finally {
      URL.revokeObjectURL = original;
    }
    assert.equal(revoked.length, 1, "the preview's memory is released as soon as the send succeeds");
    ui.q(".again").click();
    assert.equal(ui.all(".thumbs li").length, 0);
    ui.write("second");
    ui.submit();
    await until(() => ui.submissions().length === 2);
    assert.ok(!ui.submissions()[1].url.includes("with-images"));
  });

  it("keeps the images when the server says no, so the visitor can retry", async () => {
    const ui = await opened(mount({}, { handler: () => ({ status: 503, body: {} }) }));
    ui.write("try");
    choose(ui, png());
    await until(() => ui.all(".thumbs li").length === 1);
    ui.submit();
    await until(() => ui.q(".status").textContent !== "");
    assert.equal(ui.all(".thumbs li").length, 1);
    assert.equal(ui.q(".submit").disabled, false);
  });

  it("shows the server's complaint about an image next to the images", async () => {
    const detail = [{ loc: ["body", "images", 0], msg: "Only PNG, JPEG and WebP images are accepted", type: "value_error" }];
    const ui = await opened(mount({}, { handler: () => ({ status: 422, body: { detail } }) }));
    ui.write("bad");
    choose(ui, png());
    await until(() => ui.all(".thumbs li").length === 1);
    ui.submit();
    await until(() => !ui.q('[id$="-images-err"]').hidden);
    assert.equal(ui.q('[id$="-images-err"]').textContent, "Only PNG, JPEG and WebP images are accepted");
    assert.equal(ui.all(".thumbs li").length, 1);
  });

  it("hands beforeSubmit the usual payload, unchanged by images", async () => {
    let seen;
    const ui = await opened(mount({ beforeSubmit: (p) => ((seen = p), p) }));
    ui.write("hook");
    choose(ui, png());
    await until(() => ui.all(".thumbs li").length === 1);
    ui.submit();
    await until(() => ui.submissions().length === 1);
    assert.deepEqual(Object.keys(seen).sort(), ["message", "metadata"]);
  });
});

describe("the headless client", () => {
  it("limits() reads the config, and submit() takes images", async () => {
    const fetch = mockFetch((call) => (call.url.endsWith("/feedback/config") ? { status: 200, body: ON } : ok()));
    const client = g.createClient({ url: URL_, key: "pk_test", fetch });
    assert.deepEqual(await client.limits(), { maxCount: 3, maxBytes: 1000, maxEdge: 2048 });
    const result = await client.submit({ message: "hi", images: [png()] });
    assert.equal(result.ok, true);
    assert.ok(fetch.calls.at(-1).url.endsWith("/feedback/with-images"));
  });

  it("limits() is null when off, failing, or offline", async () => {
    for (const handler of [() => ({ status: 200, body: { attachments: { enabled: false } } }), () => ({ status: 500, body: {} }), () => { throw new Error("offline"); }]) {
      assert.equal(await g.createClient({ url: URL_, key: "k", fetch: mockFetch(handler) }).limits(), null);
    }
  });

  it("advertises the new capabilities", () => {
    assert.ok(g.capabilities.includes("images") && g.capabilities.includes("auto-init"));
  });
});

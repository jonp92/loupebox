import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { BUNDLE, mockFetch, ok, setupDom, teardownDom, until, wait } from "./helpers.mjs";

const g = await import(BUNDLE.href);
const URL_ = "https://feedback.example.com/v1/api";
const ON = { attachments: { enabled: true, max_count: 3, max_bytes: 100_000, max_edge: 2048 } };

let widgets = [];
let originalFetch;
let originalNavigator;
let track; // the fake screen-share track
let shared; // getDisplayMedia calls
let toBlobCalls;
let blobSize; // what a canvas "encodes" to, by mime type
let canvases; // every canvas that got a drawing context
let frame = { width: 1600, height: 900 };

function fakeContext(canvas) {
  const log = [];
  const ctx = { canvas, log, fillStyle: "", strokeStyle: "", lineWidth: 0, lineCap: "", lineJoin: "" };
  for (const m of ["drawImage", "fillRect", "beginPath", "moveTo", "lineTo", "stroke"]) {
    ctx[m] = (...a) =>
      log.push({
        m, a, fillStyle: ctx.fillStyle, strokeStyle: ctx.strokeStyle, lineWidth: ctx.lineWidth,
        widgetHidden: document.querySelector("loupebox-widget")?.hasAttribute("data-capturing"),
      });
  }
  return ctx;
}

/** The browser pieces jsdom does not have: screen sharing, video and canvas. */
function stubBrowser({ getDisplayMedia } = {}) {
  const w = window;
  originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  track = { stopped: 0, stop() { this.stopped++; } };
  shared = [];
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
  const mediaDevices = getDisplayMedia === null ? {} : { getDisplayMedia: getDisplayMedia ?? (async (o) => (shared.push(o), stream)) };
  Object.defineProperty(globalThis, "navigator", { value: { mediaDevices }, configurable: true, writable: true });
  Object.defineProperty(w.HTMLVideoElement.prototype, "videoWidth", { get: () => frame.width, configurable: true });
  Object.defineProperty(w.HTMLVideoElement.prototype, "videoHeight", { get: () => frame.height, configurable: true });
  w.HTMLVideoElement.prototype.play = async () => {};
  w.HTMLVideoElement.prototype.requestVideoFrameCallback = (cb) => setTimeout(cb, 0);
  toBlobCalls = [];
  canvases = [];
  blobSize = () => 500;
  w.HTMLCanvasElement.prototype.getContext = function () {
    if (!this.__ctx) {
      this.__ctx = fakeContext(this);
      canvases.push(this);
    }
    return this.__ctx;
  };
  w.HTMLCanvasElement.prototype.toBlob = function (cb, type, quality) {
    toBlobCalls.push({ canvas: this, type, quality });
    cb(new Blob([new Uint8Array(blobSize(type, quality))], { type }));
  };
  w.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 450, right: 800, bottom: 450 });
}

function mount(options = {}, { config = { status: 200, body: ON }, handler = () => ok() } = {}) {
  const fetch = mockFetch((call) => {
    if (call.url.endsWith("/challenge")) return { status: 200, body: { mode: "off" } };
    if (call.url.endsWith("/feedback/config")) return config;
    return handler(call);
  });
  globalThis.fetch = fetch;
  const w = g.createWidget({ url: URL_, key: "pk_test", closeDelay: 0, ...options });
  widgets.push(w);
  const root = w.element.shadowRoot;
  const q = (sel) => root.querySelector(sel);
  const all = (sel) => [...root.querySelectorAll(sel)];
  return { w, root, q, all, fetch, submissions: () => fetch.calls.filter((c) => /\/feedback(\/with-images)?$/.test(c.url)) };
}

async function opened(ui) {
  ui.w.open();
  await until(() => !ui.q(".images").hidden);
  return ui;
}

const editor = (ui) => ui.q(".editor");
const canvas = (ui) => ui.q(".editor-canvas");
const button = (ui, text) => ui.all(".editor button").find((b) => b.textContent.trim() === text);
async function startCapture(ui) {
  ui.q(".capture-image").click();
  await until(() => editor(ui));
}
const pointer = (ui, type, x, y) =>
  canvas(ui).dispatchEvent(new window.MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true, cancelable: true }));
function drag(ui, from, to) {
  pointer(ui, "pointerdown", ...from);
  pointer(ui, "pointermove", ...to);
  pointer(ui, "pointerup", ...to);
}
const key = (ui, k, opts = {}) => {
  const e = new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...opts });
  (ui.root.activeElement ?? canvas(ui)).dispatchEvent(e);
  return e;
};
/** Press Use and return what was drawn on the canvas that was encoded. */
async function use(ui) {
  button(ui, "Use screenshot").click();
  await until(() => !editor(ui));
  const call = toBlobCalls.at(-1);
  return { call, log: call.canvas.__ctx.log, boxes: call.canvas.__ctx.log.filter((e) => e.m === "fillRect") };
}

beforeEach(() => {
  globalThis.window = setupDom().window;
  originalFetch = globalThis.fetch;
  frame = { width: 1600, height: 900 };
  stubBrowser();
});
afterEach(() => {
  widgets.forEach((w) => w.destroy());
  widgets = [];
  globalThis.fetch = originalFetch;
  Object.defineProperty(globalThis, "navigator", originalNavigator);
  teardownDom();
  delete globalThis.window;
});

describe("the capture button", () => {
  it("is offered where the browser can share a screen, next to Add image", async () => {
    const ui = await opened(mount());
    const capture = ui.q(".capture-image");
    assert.equal(capture.textContent.trim(), "Capture this page");
    assert.equal(capture.type, "button");
    assert.equal(capture.previousElementSibling, ui.q(".add-image"));
  });

  it("is not offered where the browser cannot (phones, plain http)", async () => {
    stubBrowser({ getDisplayMedia: null });
    const ui = await opened(mount());
    assert.ok(ui.q(".add-image"));
    assert.equal(ui.q(".capture-image"), null);
  });

  it("is not offered when the page turned it off, or when the site takes no images", async () => {
    assert.equal((await opened(mount({ capture: false }))).q(".capture-image"), null);
    const off = mount({}, { config: { status: 200, body: { attachments: { enabled: false } } } });
    off.w.open();
    await wait(30);
    assert.equal(off.q(".capture-image"), null);
  });

  it("is disabled once the limit is reached", async () => {
    const ui = await opened(mount());
    const input = ui.q('input[type="file"]');
    const png = (n) => new File([new Uint8Array(20)], n, { type: "image/png" });
    Object.defineProperty(input, "files", { value: [png("1"), png("2"), png("3")], configurable: true });
    input.dispatchEvent(new window.Event("change", { bubbles: true }));
    await until(() => ui.all(".thumbs li").length === 3);
    assert.equal(ui.q(".capture-image").disabled, true);
  });

  it("reports itself as a capability", () => {
    assert.ok(g.capabilities.includes("capture"));
  });
});

describe("taking the picture", () => {
  it("asks for a screen share and lets go of the stream as soon as the frame is taken", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    assert.equal(shared.length, 1);
    const { width, height } = shared[0].video;
    assert.ok(width.max >= 800 && width.max <= 3840 && height.max >= 800 && height.max <= 2160, "up to the screen, never above 4K");
    assert.equal(shared[0].audio, false);
    assert.equal(track.stopped, 1, "the browser's sharing indicator goes away at once");
    assert.equal(ui.w.element.hasAttribute("data-capturing"), false, "the widget is back");
  });

  it("is hidden at the moment the frame is taken, so it is not in the picture", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    const frameCanvas = canvases.find((c) => c.__ctx.log.some((e) => e.m === "drawImage" && e.a[0]?.tagName === "VIDEO"));
    assert.ok(frameCanvas, "the frame came from the video");
    const draw = frameCanvas.__ctx.log.find((e) => e.m === "drawImage" && e.a[0]?.tagName === "VIDEO");
    assert.equal(draw.widgetHidden, true);
    // ...and it is not hidden for the editor (which needs to be seen) or when idle.
    assert.equal(ui.w.element.hasAttribute("data-capturing"), false);
  });

  it("says nothing when the visitor cancels the browser's picker", async () => {
    stubBrowser({ getDisplayMedia: async () => { throw new DOMException("denied", "NotAllowedError"); } });
    const ui = await opened(mount());
    ui.q(".capture-image").click();
    await until(() => !ui.q(".capture-image").disabled);
    assert.equal(editor(ui), null);
    assert.equal(ui.q(".status").textContent, "");
    assert.equal(ui.root.activeElement, ui.q(".capture-image"), "focus comes back to the button");
  });

  it("says so when capturing fails for another reason, and Add image still works", async () => {
    stubBrowser({ getDisplayMedia: async () => { throw new DOMException("no", "NotFoundError"); } });
    const ui = await opened(mount());
    ui.q(".capture-image").click();
    await until(() => ui.q(".status").textContent !== "");
    assert.equal(ui.q(".status").textContent, "We couldn't capture the screen. You can still add an image.");
    assert.equal(ui.q(".status").getAttribute("data-kind"), "error");
    assert.equal(ui.q(".add-image").disabled, false);
  });

  it("fails cleanly when the stream has no picture", async () => {
    frame = { width: 0, height: 0 };
    const ui = await opened(mount());
    ui.q(".capture-image").click();
    await until(() => ui.q(".status").textContent !== "");
    assert.equal(track.stopped, 1);
    assert.equal(editor(ui), null);
  });

  it("is not available while one is under way", async () => {
    const ui = await opened(mount());
    ui.q(".capture-image").click();
    ui.q(".capture-image").click();
    await until(() => editor(ui));
    assert.equal(shared.length, 1);
  });
});

describe("the redact editor", () => {
  it("opens over the page as a modal dialog with Hide selected and the canvas focused", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    const dialog = editor(ui);
    assert.equal(dialog.getAttribute("role"), "dialog");
    assert.equal(dialog.getAttribute("aria-modal"), "true");
    assert.equal(ui.root.getElementById(dialog.getAttribute("aria-labelledby")).textContent, "Hide anything private");
    assert.equal(ui.root.activeElement, canvas(ui));
    assert.deepEqual(ui.all(".tool").map((b) => [b.textContent.trim(), b.getAttribute("aria-pressed")]), [["Hide", "true"], ["Highlight", "false"]]);
    assert.equal(ui.q(".tools").getAttribute("aria-label"), "Tool");
    assert.ok(ui.root.getElementById(canvas(ui).getAttribute("aria-describedby")).textContent.includes("arrow keys"));
  });

  it("puts the buttons under the picture", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    const kids = [...ui.q(".editor-box").children].map((c) => c.className || c.tagName.toLowerCase());
    assert.ok(kids.indexOf("editor-stage") < kids.indexOf("editor-bar"));
  });

  it("burns a solid black box into the picture that is sent, at the right place", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    drag(ui, [100, 100], [300, 200]); // the canvas is shown at 800x450: a quarter of the width, from 12.5%
    const { boxes, call } = await use(ui);
    assert.equal(boxes.length, 1);
    const [x, y, w, h] = boxes[0].a;
    assert.deepEqual([x, y, w, h].map(Math.round), [200, 200, 400, 200]); // 1600x900 picture
    assert.equal(boxes[0].fillStyle, "#000");
    assert.equal(call.type, "image/png");
  });

  it("draws the box at the picture's real size, not the editing size", async () => {
    frame = { width: 4000, height: 2000 }; // more than the site takes: 2048 on the long side
    const ui = await opened(mount());
    await startCapture(ui);
    drag(ui, [0, 0], [400, 225]); // the top-left quarter of the screen
    const { boxes, call } = await use(ui);
    assert.deepEqual([call.canvas.width, call.canvas.height], [2048, 1024]);
    assert.deepEqual(boxes[0].a.map(Math.round), [0, 0, 1024, 512]);
  });

  it("lets a box be drawn in any direction", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    drag(ui, [300, 200], [100, 100]);
    const { boxes } = await use(ui);
    assert.deepEqual(boxes[0].a.map(Math.round), [200, 200, 400, 200]);
  });

  it("keeps boxes inside the picture", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    drag(ui, [700, 400], [2000, 2000]);
    const { boxes } = await use(ui);
    const [x, y, w, h] = boxes[0].a;
    assert.ok(x + w <= 1600.5 && y + h <= 900.5);
  });

  it("ignores a stray click", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    drag(ui, [100, 100], [101, 101]);
    assert.equal((await use(ui)).boxes.length, 0);
  });

  it("highlights with a translucent pen", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    button(ui, "Highlight").click();
    assert.equal(button(ui, "Highlight").getAttribute("aria-pressed"), "true");
    assert.equal(button(ui, "Hide").getAttribute("aria-pressed"), "false");
    pointer(ui, "pointerdown", 100, 100);
    pointer(ui, "pointermove", 200, 150);
    pointer(ui, "pointermove", 300, 120);
    pointer(ui, "pointerup", 300, 120);
    const { log } = await use(ui);
    const stroke = log.find((e) => e.m === "stroke");
    assert.equal(stroke.strokeStyle, "rgba(255, 214, 10, 0.5)");
    assert.ok(stroke.lineWidth > 0);
    assert.deepEqual(log.filter((e) => e.m === "lineTo").length, 2);
    assert.equal(log.filter((e) => e.m === "fillRect").length, 0, "a highlight is not a box");
  });

  it("undoes the last shape and clears them all", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    assert.equal(button(ui, "Undo").disabled, true);
    assert.equal(button(ui, "Clear").disabled, true);
    drag(ui, [10, 10], [100, 100]);
    assert.equal(button(ui, "Undo").disabled, false);
    assert.equal(button(ui, "Clear").disabled, false);
    button(ui, "Undo").click();
    assert.equal(button(ui, "Undo").disabled, true, "nothing left to undo");
    drag(ui, [400, 100], [500, 200]);
    drag(ui, [10, 300], [100, 400]);
    button(ui, "Clear").click();
    assert.equal(button(ui, "Clear").disabled, true);
    assert.equal((await use(ui)).boxes.length, 0);
  });

  it("shows exactly the boxes that were kept after an undo", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    drag(ui, [10, 10], [100, 100]);
    drag(ui, [200, 200], [300, 300]);
    button(ui, "Undo").click();
    const { boxes } = await use(ui);
    assert.equal(boxes.length, 1);
    assert.deepEqual(boxes[0].a.map(Math.round), [20, 20, 180, 180]);
  });

  it("cancel throws the capture away", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    drag(ui, [100, 100], [300, 200]);
    button(ui, "Cancel").click();
    await until(() => !editor(ui));
    assert.equal(ui.all(".thumbs li").length, 0);
    assert.equal(ui.q('[id$="-images-err"]').hidden, true, "cancelling is not an error");
    assert.equal(toBlobCalls.length, 0, "nothing was encoded, so nothing can be sent");
    assert.equal(ui.root.activeElement, ui.q(".capture-image"));
  });

  it("Escape cancels it too", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    key(ui, "Escape");
    await until(() => !editor(ui));
    assert.equal(ui.all(".thumbs li").length, 0);
  });

  it("releases the full-size capture when it closes, whether used or cancelled", async () => {
    const isFrame = (c) => c.__ctx.log.some((e) => e.m === "drawImage" && e.a[0]?.tagName === "VIDEO");
    const ui = await opened(mount());
    await startCapture(ui);
    const first = canvases.find(isFrame);
    assert.equal(first.width, 1600);
    button(ui, "Cancel").click();
    await until(() => !editor(ui));
    assert.equal(first.width + first.height, 0);
    await startCapture(ui);
    const second = canvases.filter(isFrame).at(-1);
    await use(ui);
    assert.equal(second.width + second.height, 0);
  });
});

describe("keeping the result", () => {
  it("adds the edited picture like any other image, and sends it", async () => {
    const ui = await opened(mount());
    ui.q("textarea").value = "look at this";
    await startCapture(ui);
    drag(ui, [100, 100], [300, 200]);
    await use(ui);
    await until(() => ui.all(".thumbs li").length === 1);
    assert.equal(ui.q(".image-row .hint").textContent, "1 of 3 images");
    assert.equal(ui.root.activeElement, ui.q(".capture-image"));
    ui.q("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
    await until(() => ui.submissions().length === 1);
    const [call] = ui.submissions();
    assert.ok(call.url.endsWith("/feedback/with-images"));
    const [file] = call.form.getAll("images");
    assert.equal(file.name, "screenshot.png");
    assert.equal(file.type, "image/png");
  });

  it("falls back to JPEG when the PNG is too big for the site", async () => {
    blobSize = (type) => (type === "image/png" ? 500_000 : 40_000); // the site takes 100 000 bytes
    const ui = await opened(mount());
    await startCapture(ui);
    await use(ui);
    assert.deepEqual(toBlobCalls.map((c) => c.type), ["image/png", "image/jpeg"]);
    await until(() => ui.all(".thumbs li").length === 1);
  });

  it("tries a smaller JPEG before giving up", async () => {
    blobSize = (type, quality) => (type === "image/jpeg" && quality === 0.7 ? 40_000 : 500_000);
    const ui = await opened(mount());
    await startCapture(ui);
    await use(ui);
    assert.deepEqual(toBlobCalls.map((c) => [c.type, c.quality]), [["image/png", undefined], ["image/jpeg", 0.85], ["image/jpeg", 0.7]]);
    await until(() => ui.all(".thumbs li").length === 1);
  });

  it("says so, and adds nothing, when it cannot be made small enough", async () => {
    blobSize = () => 500_000;
    const ui = await opened(mount());
    await startCapture(ui);
    await use(ui);
    await until(() => !ui.q('[id$="-images-err"]').hidden);
    assert.match(ui.q('[id$="-images-err"]').textContent, /too large/);
    assert.equal(ui.all(".thumbs li").length, 0);
  });

  it("a captured picture counts toward the limit", async () => {
    const ui = await opened(mount());
    for (let i = 0; i < 3; i++) {
      await startCapture(ui);
      await use(ui);
      await until(() => ui.all(".thumbs li").length === i + 1);
    }
    assert.equal(ui.q(".capture-image").disabled, true);
  });
});

describe("without a mouse", () => {
  it("draws a box with the arrow keys and Enter", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    for (let i = 0; i < 5; i++) key(ui, "ArrowRight"); // 0.5 -> 0.6
    for (let i = 0; i < 5; i++) key(ui, "ArrowDown");
    key(ui, "Enter");
    assert.equal(ui.q('[role="status"].sr-only').textContent, "Corner set. Move to the opposite corner, then press Enter.");
    for (let i = 0; i < 5; i++) key(ui, "ArrowRight");
    for (let i = 0; i < 5; i++) key(ui, "ArrowDown");
    key(ui, "Enter");
    assert.equal(ui.q('[role="status"].sr-only').textContent, "Added.");
    const { boxes } = await use(ui);
    assert.equal(boxes.length, 1);
    const [x, y, w, h] = boxes[0].a;
    assert.deepEqual([x, y, w, h].map((n) => Math.round(n)), [960, 540, 160, 90]);
  });

  it("moves in bigger steps with Shift, and stays inside the picture", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    for (let i = 0; i < 20; i++) key(ui, "ArrowLeft", { shiftKey: true });
    key(ui, "Enter");
    for (let i = 0; i < 3; i++) key(ui, "ArrowDown", { shiftKey: true });
    for (let i = 0; i < 3; i++) key(ui, "ArrowRight", { shiftKey: true });
    key(ui, "Enter");
    const [x, y, w, h] = (await use(ui)).boxes[0].a;
    assert.equal(x, 0);
    assert.ok(Math.abs(w - 0.3 * 1600) < 1 && Math.abs(h - 0.3 * 900) < 1 && y > 0);
  });

  it("highlights with Enter to start and stop", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    button(ui, "Highlight").click();
    canvas(ui).focus();
    key(ui, "Enter");
    key(ui, "ArrowRight");
    key(ui, "ArrowRight");
    key(ui, "Enter");
    const { log } = await use(ui);
    assert.ok(log.some((e) => e.m === "stroke"));
  });

  it("Escape cancels the shape first, and only then the editor", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    key(ui, "Enter");
    key(ui, "ArrowRight");
    key(ui, "Escape");
    assert.ok(editor(ui), "the editor is still open");
    key(ui, "Enter"); // start again
    key(ui, "Escape");
    key(ui, "Escape");
    await until(() => !editor(ui));
  });

  it("keeps Tab inside the editor", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    const shift = (e) => key(ui, "Tab", { shiftKey: e });
    ui.root.activeElement.blur?.();
    const focusables = ui.all(".editor button, .editor canvas").filter((e) => !e.disabled);
    focusables.at(-1).focus();
    const forward = key(ui, "Tab");
    assert.equal(forward.defaultPrevented, true);
    assert.equal(ui.root.activeElement, focusables[0]);
    const back = shift(true);
    assert.equal(back.defaultPrevented, true);
    assert.equal(ui.root.activeElement, focusables.at(-1));
  });
});

describe("while the widget changes underneath", () => {
  it("destroy() closes the editor and sends nothing", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    ui.w.destroy();
    assert.equal(ui.w.element.isConnected, false);
    await wait(20);
    assert.equal(toBlobCalls.length, 0);
  });

  it("update() closes the editor instead of stranding it", async () => {
    const ui = await opened(mount());
    await startCapture(ui);
    ui.w.update({ theme: "dark" });
    await wait(20);
    assert.equal(ui.root.querySelector(".editor"), null);
    assert.equal(ui.q(".capture-image").disabled, false, "the button is not left waiting for an editor that is gone");
    await startCapture(ui); // and it can be used again
    assert.ok(editor(ui));
  });
});

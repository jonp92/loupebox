import { JSDOM } from "jsdom";

export const BUNDLE = new URL("../../dist/widget/v1/loupebox.js", import.meta.url);

/** A fresh page for each test. Only what the widget touches is exposed as globals. */
export function setupDom(url = "https://app.example.com/pricing?x=1") {
  const dom = new JSDOM("<!doctype html><html><body><div id='slot'></div></body></html>", { url });
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  return dom;
}

export function teardownDom() {
  delete globalThis.document;
  delete globalThis.location;
}

/** A fetch stand-in. `handler(url, init)` returns a Response-like or throws. Calls are recorded. */
export function mockFetch(handler) {
  const calls = [];
  const fn = async (url, init = {}) => {
    const call = { url: String(url), init, body: init.body ? JSON.parse(init.body) : undefined };
    calls.push(call);
    const out = await handler(call, calls.length);
    if (out instanceof Response) return out;
    return json(out.status ?? 200, out.body ?? {}, out.headers);
  };
  fn.calls = calls;
  return fn;
}

export const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

export const ok = () => ({ status: 201, body: { id: "11111111-1111-1111-1111-111111111111" } });

export const wait = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));
export async function until(fn, ms = 2000) {
  const start = Date.now();
  while (Date.now() - start < ms) {
    const value = await fn();
    if (value) return value;
    await wait(10);
  }
  throw new Error("timed out waiting for condition");
}

export function captureWarnings() {
  const seen = [];
  const original = console.warn;
  console.warn = (...args) => seen.push(args.join(" "));
  return { seen, restore: () => (console.warn = original) };
}

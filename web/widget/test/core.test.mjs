import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { BUNDLE, captureWarnings, json, mockFetch, ok } from "./helpers.mjs";

// Imported before any DOM exists: the module must be safe to load on a server.
const g = await import(BUNDLE.href);

const KEY = "pk_test";
const URL_ = "https://feedback.example.com/v1/api";
const sha = (text) => createHash("sha256").update(text).digest();

function leadingZeroBits(digest) {
  const value = BigInt("0x" + digest.toString("hex"));
  return value === 0n ? digest.length * 8 : digest.length * 8 - value.toString(2).length;
}

describe("module", () => {
  it("loads without a DOM and exposes a stable public surface", () => {
    assert.deepEqual(
      Object.keys(g).sort(),
      ["GanymedeConfigError", "VERSION", "capabilities", "createClient", "createWidget", "defaultIssueTypes", "defaultStrings", "solveProofOfWork"].sort(),
    );
    assert.match(g.VERSION, /^\d+\.\d+\.\d+$/);
    for (const feature of ["issue-types", "challenge-pow", "headless-client", "events"]) assert.ok(g.capabilities.includes(feature), feature);
  });

  it("createWidget on a server says so instead of crashing obscurely", () => {
    assert.throws(() => g.createWidget({ url: URL_, key: KEY }), (e) => e instanceof g.GanymedeConfigError && /browser/.test(e.message));
  });

  it("never uses APIs that would run page-supplied strings as code or markup", () => {
    const source = readFileSync(BUNDLE, "utf8");
    for (const banned of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "dangerouslySet"]) {
      assert.ok(!source.includes(banned), `bundle contains ${banned}`);
    }
  });

  it("ships the issue types and strings as data a page can read and extend", () => {
    assert.deepEqual(g.defaultIssueTypes.map((t) => t.id), ["bug", "idea", "question", "praise"]);
    assert.equal(typeof g.defaultStrings.submit, "string");
  });
});

describe("proof of work", () => {
  it("finds valid proofs (platform SHA-256)", async () => {
    for (const bits of [1, 4, 8, 12]) {
      const proof = await g.solveProofOfWork("tok", bits);
      assert.ok(proof.startsWith("tok:"));
      assert.ok(leadingZeroBits(sha(proof)) >= bits, `${bits} bits`);
    }
  });

  it("works without crypto.subtle (the pure-JS fallback agrees with Node's SHA-256)", async () => {
    const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { value: { subtle: undefined }, configurable: true });
    try {
      for (const bits of [4, 10, 13]) {
        const proof = await g.solveProofOfWork("a-longer-token-value-" + "x".repeat(70), bits);
        assert.ok(leadingZeroBits(sha(proof)) >= bits, `${bits} bits`);
      }
    } finally {
      Object.defineProperty(globalThis, "crypto", original);
    }
  });

  it("can be aborted", async () => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 60);
    await assert.rejects(g.solveProofOfWork("tok", 40, controller.signal), { name: "AbortError" });
  });
});

describe("client", () => {
  const make = (fetchImpl, extra = {}) => g.createClient({ url: URL_ + "/", key: KEY, fetch: fetchImpl, ...extra });
  const off = { status: 200, body: { mode: "off" } };

  it("sends the contract: headers, anonymous, only allowed fields", async () => {
    const fetch = mockFetch((call) => (call.url.endsWith("/challenge") ? off : ok()));
    const result = await make(fetch).submit({
      message: "hi", rating: 4, name: "Ada", email: "ada@example.com", issueType: "bug", metadata: { plan: "pro" },
      pageUrl: "https://app.example.com/x",
    });
    assert.deepEqual(result, { ok: true, id: "11111111-1111-1111-1111-111111111111" });
    const send = fetch.calls.at(-1);
    assert.equal(send.url, `${URL_}/feedback`); // trailing slash trimmed, prefix kept
    assert.equal(send.init.method, "POST");
    assert.equal(send.init.credentials, "omit");
    assert.equal(send.init.headers["X-API-Key"], KEY);
    assert.equal(send.init.headers["Content-Type"], "application/json");
    assert.ok(!("Authorization" in send.init.headers));
    assert.deepEqual(send.body, {
      message: "hi", rating: 4, name: "Ada", email: "ada@example.com", page_url: "https://app.example.com/x",
      metadata: { widget_version: g.VERSION, issue_type: "bug", plan: "pro" }, website: "",
    });
  });

  it("omits empty optionals and a non-http page URL (a file:// page would be a 422)", async () => {
    const fetch = mockFetch((call) => (call.url.endsWith("/challenge") ? off : ok()));
    await make(fetch).submit({ message: "hi", email: "", name: "", pageUrl: undefined });
    assert.deepEqual(Object.keys(fetch.calls.at(-1).body).sort(), ["message", "metadata", "website"]);
  });

  it("keeps its own metadata keys, caps keys and value length, drops non-primitives", async () => {
    const fetch = mockFetch((call) => (call.url.endsWith("/challenge") ? off : ok()));
    const metadata = { issue_type: "spoofed", widget_version: "9.9.9", long: "x".repeat(400), obj: { a: 1 }, fn: () => 1, flag: true, nothing: null };
    for (let i = 0; i < 30; i++) metadata[`k${i}`] = i;
    await make(fetch).submit({ message: "hi", issueType: "idea", metadata });
    const sent = fetch.calls.at(-1).body.metadata;
    assert.equal(sent.issue_type, "idea");
    assert.equal(sent.widget_version, g.VERSION);
    assert.equal(sent.long.length, 256);
    assert.ok(!("obj" in sent) && !("fn" in sent));
    assert.equal(Object.keys(sent).length, 20);
  });

  it("asks for a challenge first and solves a proof-of-work one", async () => {
    const fetch = mockFetch((call) =>
      call.url.endsWith("/challenge") ? { status: 200, body: { mode: "pow", algorithm: "sha256", token: "abc.def", bits: 10 } } : ok());
    assert.equal((await make(fetch).submit({ message: "hi" })).ok, true);
    assert.equal(fetch.calls[0].url, `${URL_}/feedback/challenge`);
    assert.equal(fetch.calls[0].init.headers["X-API-Key"], KEY);
    const proof = fetch.calls[1].body.challenge;
    assert.ok(proof.startsWith("abc.def:") && leadingZeroBits(sha(proof)) >= 10);
  });

  it("retries once with a fresh challenge when the proof is rejected, then gives up", async () => {
    let feedbackCalls = 0;
    const fetch = mockFetch((call) => {
      if (call.url.endsWith("/challenge")) return { status: 200, body: { mode: "pow", algorithm: "sha256", token: `t${fetch.calls.length}`, bits: 4 } };
      feedbackCalls++;
      return feedbackCalls === 1 ? { status: 403, body: { detail: "Challenge failed" } } : ok();
    });
    assert.equal((await make(fetch).submit({ message: "hi" })).ok, true);
    assert.deepEqual(fetch.calls.map((c) => c.url.split("/").pop()), ["challenge", "feedback", "challenge", "feedback"]);

    const always = mockFetch((call) =>
      call.url.endsWith("/challenge") ? { status: 200, body: { mode: "pow", algorithm: "sha256", token: "t", bits: 4 } } : { status: 403, body: { detail: "Challenge failed" } });
    assert.deepEqual(await make(always).submit({ message: "hi" }), { ok: false, reason: "rejected" });
    assert.equal(always.calls.length, 4); // one retry, not a loop
  });

  it("does not retry a plain Forbidden (bad key or origin)", async () => {
    const fetch = mockFetch((call) => (call.url.endsWith("/challenge") ? off : { status: 403, body: { detail: "Forbidden" } }));
    assert.deepEqual(await make(fetch).submit({ message: "hi" }), { ok: false, reason: "rejected" });
    assert.equal(fetch.calls.length, 2);
  });

  it("reports a challenge kind it doesn't know instead of sending without proof", async () => {
    const fetch = mockFetch(() => ({ status: 200, body: { mode: "captcha-9000", token: "t" } }));
    assert.deepEqual(await make(fetch).submit({ message: "hi" }), { ok: false, reason: "challenge_unsupported" });
    assert.equal(fetch.calls.length, 1);
  });

  it("maps 422 to field messages, 429 to a wait, and network failures", async () => {
    const invalid = mockFetch((call) => (call.url.endsWith("/challenge") ? off : {
      status: 422, body: { detail: [{ loc: ["body", "email"], msg: "value is not a valid email address" }, { loc: ["body", "page_url"], msg: "Value error, page_url must be http(s)" }] },
    }));
    const r = await make(invalid).submit({ message: "hi" });
    assert.deepEqual(r, { ok: false, reason: "invalid", fields: { email: "value is not a valid email address", pageUrl: "page_url must be http(s)" } });

    const limited = mockFetch((call) => (call.url.endsWith("/challenge") ? off : new Response("{}", { status: 429, headers: { "Retry-After": "42" } })));
    assert.deepEqual(await make(limited).submit({ message: "hi" }), { ok: false, reason: "rate_limited", retryAfter: 42 });

    const challengeLimited = mockFetch(() => new Response("{}", { status: 429, headers: { "Retry-After": "7" } }));
    assert.deepEqual(await make(challengeLimited).submit({ message: "hi" }), { ok: false, reason: "rate_limited", retryAfter: 7 });

    const down = mockFetch(() => { throw new TypeError("Failed to fetch"); });
    assert.deepEqual(await make(down).submit({ message: "hi" }), { ok: false, reason: "network" });
  });

  it("gives up on a hung request", async () => {
    const hung = (_url, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))));
    const started = Date.now();
    assert.deepEqual(await make(hung, { timeout: 50 }).submit({ message: "hi" }), { ok: false, reason: "network" });
    assert.ok(Date.now() - started < 1000);
  });
});

describe("options", () => {
  const widgetFor = async (options) => {
    const { setupDom } = await import("./helpers.mjs");
    setupDom();
    return g.createWidget({ url: URL_, key: KEY, ...options });
  };

  it("rejects what can't work, with messages that say what to fix", async () => {
    const { setupDom } = await import("./helpers.mjs");
    setupDom();
    const bad = (options, pattern) => assert.throws(() => g.createWidget(options), (e) => e instanceof g.GanymedeConfigError && pattern.test(e.message));
    bad({ url: URL_ }, /"key" is required/);
    bad({ key: KEY, url: "feedback.example.com" }, /"url" must be/);
    bad({ url: URL_, key: KEY, mode: "modal" }, /"mode" must be one of/);
    bad({ url: URL_, key: KEY, mode: "inline" }, /"target" is required/);
    bad({ url: URL_, key: KEY, issueTypes: [{ id: "Bad Id", label: "x" }] }, /issue type ids/);
    bad({ url: URL_, key: KEY, issueTypes: [{ id: "a", label: "x" }, { id: "a", label: "y" }] }, /duplicate/);
    bad({ url: URL_, key: KEY, issueTypes: [{ id: "a", label: "" }] }, /label/);
    bad({ url: URL_, key: KEY, defaultIssueType: "nope" }, /defaultIssueType/);
    bad({ url: URL_, key: KEY, extraFields: [{ id: "issue_type", label: "x" }] }, /reserved/);
    bad({ url: URL_, key: KEY, extraFields: [{ id: "s", label: "x", type: "select" }] }, /needs options/);
    bad({ url: URL_, key: KEY, fields: { email: "maybe" } }, /fields\.email/);
    bad({ url: URL_, key: KEY, closeDelay: -1 }, /closeDelay/);
  });

  it("ignores options it doesn't know with a warning, so newer config degrades gracefully", async () => {
    const warnings = captureWarnings();
    try {
      const w = await widgetFor({ screenshots: true, strings: { future: "x" }, colors: { sparkle: "red" } });
      assert.ok(w.element.isConnected);
      assert.ok(warnings.seen.some((m) => /unknown option "screenshots"/.test(m)));
      assert.ok(warnings.seen.some((m) => /unknown string "future"/.test(m)));
      assert.ok(warnings.seen.some((m) => /unknown color "sparkle"/.test(m)));
      w.destroy();
    } finally {
      warnings.restore();
    }
  });

  it("refuses colors and fonts that could carry anything but a color or a font name", async () => {
    const warnings = captureWarnings();
    try {
      const w = await widgetFor({ colors: { accent: "red; background: url(//evil)", text: "#112233" }, fontFamily: "x}</style>", issueTypes: [{ id: "a", label: "A", color: "url(x)" }] });
      assert.equal(w.element.style.getPropertyValue("--gm-accent"), "");
      assert.equal(w.element.style.getPropertyValue("--gm-text"), "#112233");
      assert.equal(warnings.seen.filter((m) => /ignoring/.test(m)).length, 3);
      w.destroy();
    } finally {
      warnings.restore();
    }
  });

  it("warns when the url is missing the /v1/api prefix", async () => {
    const warnings = captureWarnings();
    try {
      (await widgetFor({ url: "https://feedback.example.com" })).destroy();
      assert.ok(warnings.seen.some((m) => /\/v1\/api/.test(m)));
    } finally {
      warnings.restore();
    }
  });
});

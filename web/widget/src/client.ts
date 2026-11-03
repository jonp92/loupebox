import { solveProofOfWork } from "./challenge";
import { MAX_METADATA_KEYS, type MetadataValue } from "./options";
import { VERSION } from "./version";

export interface FeedbackInput {
  message: string;
  rating?: number;
  name?: string;
  email?: string;
  /** Sent as `metadata.issue_type`. */
  issueType?: string;
  /** Extra data. `issue_type` and `widget_version` are set by the widget and can't be overridden. */
  metadata?: Record<string, MetadataValue>;
  /** Defaults to `location.href` on http(s) pages. */
  pageUrl?: string;
  /** Honeypot value, passed through untouched (empty for humans). */
  website?: string;
}

export type SubmitResult =
  | { ok: true; id: string }
  | {
      ok: false;
      reason: "network" | "rate_limited" | "invalid" | "rejected" | "challenge_unsupported";
      /** Seconds to wait, when the server said. */
      retryAfter?: number;
      /** Server-side validation messages by field name (message, email, name, rating, ...). */
      fields?: Record<string, string>;
    };

export interface ClientOptions {
  url: string;
  key: string;
  /** For tests and unusual runtimes. Defaults to the global `fetch`. */
  fetch?: typeof fetch;
  /** Milliseconds before a request is abandoned (default 20000). */
  timeout?: number;
}

const FIELD_NAMES: Record<string, string> = { page_url: "pageUrl" };

function metadataFor(input: FeedbackInput): Record<string, MetadataValue> {
  const out: Record<string, MetadataValue> = {};
  for (const [key, value] of Object.entries(input.metadata ?? {})) {
    if (key === "issue_type" || key === "widget_version" || key.length > 64) continue;
    if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
      out[key] = typeof value === "string" ? value.slice(0, 256) : value;
    }
  }
  const ours: Record<string, MetadataValue> = { widget_version: VERSION };
  if (input.issueType) ours.issue_type = input.issueType;
  // Ours first so they always survive the key cap.
  const all = { ...ours, ...out };
  return Object.fromEntries(Object.entries(all).slice(0, MAX_METADATA_KEYS));
}

function defaultPageUrl(): string | undefined {
  const href = typeof location === "undefined" ? "" : location.href;
  return /^https?:\/\//i.test(href) ? href.slice(0, 2048) : undefined; // file:// pages would be a 422
}

/** The headless client: everything the widget sends, without any UI. */
export function createClient(options: ClientOptions) {
  const base = options.url.replace(/\/+$/, "");
  const doFetch = options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args));

  async function request(path: string, body?: unknown): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeout ?? 20_000);
    try {
      return await doFetch(`${base}${path}`, {
        method: "POST",
        mode: "cors",
        credentials: "omit", // anonymous endpoint: no cookies, no Authorization
        headers: { "Content-Type": "application/json", "X-API-Key": options.key },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  /** The proof for this submission, `undefined` when the site doesn't ask for one, or a failure. */
  async function challenge(): Promise<{ proof?: string } | Exclude<SubmitResult, { ok: true }>> {
    const res = await request("/feedback/challenge");
    if (!res.ok) return failure(res, await readJson(res));
    const info = (await readJson(res)) as { mode?: string; algorithm?: string; token?: string; bits?: number };
    if (!info.mode || info.mode === "off") return {};
    if (info.mode === "pow" && info.algorithm === "sha256" && typeof info.token === "string" && typeof info.bits === "number") {
      return { proof: await solveProofOfWork(info.token, info.bits) };
    }
    return { ok: false, reason: "challenge_unsupported" }; // a newer kind of challenge than this version knows
  }

  async function send(input: FeedbackInput, proof: string | undefined): Promise<Response> {
    const pageUrl = input.pageUrl ?? defaultPageUrl();
    return request("/feedback", {
      message: input.message,
      ...(input.rating ? { rating: input.rating } : {}),
      ...(input.name ? { name: input.name } : {}),
      ...(input.email ? { email: input.email } : {}),
      ...(pageUrl ? { page_url: pageUrl } : {}),
      metadata: metadataFor(input),
      website: input.website ?? "",
      ...(proof ? { challenge: proof } : {}),
    });
  }

  return {
    /** Send one piece of feedback. Never throws: failures come back as `{ ok: false, reason }`. */
    async submit(input: FeedbackInput): Promise<SubmitResult> {
      try {
        // Retry once with a fresh challenge if the proof was rejected (expired or already used).
        for (let attempt = 0; attempt < 2; attempt++) {
          const c = await challenge();
          if ("ok" in c) return c;
          const res = await send(input, c.proof);
          if (res.ok) return { ok: true, id: String(((await readJson(res)) as { id?: string }).id ?? "") };
          const body = await readJson(res);
          const failed = c.proof && res.status === 403 && /challenge/i.test(String((body as { detail?: unknown }).detail));
          if (!(failed && attempt === 0)) return failure(res, body);
        }
        return { ok: false, reason: "rejected" };
      } catch {
        return { ok: false, reason: "network" }; // offline, CORS (origin not allowed), timeout, DNS
      }
    },
  };
}

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return {};
  }
}

function failure(res: Response, body: unknown): Exclude<SubmitResult, { ok: true }> {
  if (res.status === 429) {
    const retryAfter = Number(res.headers.get("Retry-After")) || undefined;
    return { ok: false, reason: "rate_limited", retryAfter };
  }
  if (res.status === 422) {
    const fields: Record<string, string> = {};
    const detail = (body as { detail?: unknown }).detail;
    if (Array.isArray(detail)) {
      for (const item of detail as { loc?: unknown[]; msg?: string }[]) {
        const raw = String(item.loc?.[item.loc.length - 1] ?? "");
        if (raw && raw !== "body") fields[FIELD_NAMES[raw] ?? raw] ??= String(item.msg ?? "").replace(/^Value error, /, "");
      }
    }
    return { ok: false, reason: "invalid", fields };
  }
  return { ok: false, reason: "rejected" };
}

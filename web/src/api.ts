declare global {
  interface Window {
    __CONFIG__?: { API_URL?: string };
  }
}

// Origin of the API server. Runtime config (container) wins over the build-time dev default.
export const API_URL: string = (
  window.__CONFIG__?.API_URL || import.meta.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");
// The server mounts every route under this prefix (settings.api_prefix).
export const API_PREFIX = "/v1/api";
const BASE = API_URL + API_PREFIX;

export type Role = "viewer" | "editor" | "admin";
export type Status = "new" | "read" | "archived" | "spam";

export interface Profile {
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
}
export interface Me extends Profile {
  id: string;
  is_superadmin: boolean;
  totp_enabled: boolean;
  totp_required: boolean; // 2FA is required and this account has none: only setup is open
  recovery_codes_left: number;
  memberships: { site_id: string; role: Role }[];
}
export interface Site {
  id: string;
  name: string;
  public_key: string;
  allowed_origins: string[];
  is_active: boolean;
  daily_limit: number;
  challenge_mode: string; // "off" or a verifier key
  challenge_config: Record<string, unknown>;
  attachments_enabled: boolean;
  attachments_ready: boolean; // false while the image storage is not fully set up
  attachment_max_count: number; // server-wide limits, read-only
  attachment_max_bytes: number;
  retention_delete_days: number | null; // null: keep forever
  retention_strip_email_days: number | null;
  my_role: Role | null;
}
export interface DashboardSite extends Site {
  new_count: number;
}
export interface DashboardItem extends Feedback {
  site_id: string;
  site_name: string;
}
export interface Dashboard {
  new_total: number;
  new_24h: number;
  received_total: number;
  sites_with_new: number;
  sites: DashboardSite[];
  recent_new: DashboardItem[];
  assigned_total: number;
  assigned: DashboardItem[];
}
export interface Feedback {
  id: string;
  message: string;
  rating: number | null;
  name: string | null;
  email: string | null;
  page_url: string | null;
  metadata: Record<string, unknown>;
  status: Status;
  user_agent: string | null;
  created_at: string;
  assignee_id: string | null;
  assignee_name: string | null;
  tags: string[];
  note_count: number;
  reply_count: number;
  attachment_count: number;
}
export interface Attachment {
  id: string;
  content_type: string;
  size: number;
  width: number;
  height: number;
  created_at: string;
}
export interface Assignee {
  user_id: string;
  email: string;
  name: string;
}
export interface Note {
  id: string;
  author_id: string | null;
  author_name: string | null;
  body: string;
  created_at: string;
}
export interface Reply {
  id: string;
  author_id: string | null;
  author_name: string | null;
  direction: "outbound" | "inbound";
  source: "ui" | "email";
  body: string;
  status: "sent" | "failed";
  error: string | null;
  retryable: boolean;
  created_at: string;
}
export interface ReplyThread {
  available: boolean;
  inbound: boolean;
  items: Reply[];
}
export interface Member extends Profile {
  user_id: string;
  role: Role;
}
export interface User extends Profile {
  id: string;
  is_superadmin: boolean;
  is_active: boolean;
  totp_enabled: boolean;
}

/** Avatar URLs from the API are paths on the API origin. */
export function avatarSrc(url: string | null | undefined): string | null {
  return url ? API_URL + url : null; // server-supplied paths already include the prefix
}

export function displayName(p: Pick<Profile, "email" | "first_name" | "last_name">): string {
  return `${p.first_name} ${p.last_name}`.trim() || p.email;
}

export interface AuditEvent {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_email: string;
  action: string; // "<group>.<verb>"
  target_type: string;
  target_id: string;
  site_id: string | null;
  site_name: string | null;
  summary: string;
  details: Record<string, unknown>;
}

/** One row of System settings. Secrets never come back: value, env_value and default are null for them. */
export interface SystemSetting {
  key: string;
  group: string;
  label: string;
  help: string;
  type: "integer" | "string" | "boolean" | "list";
  minimum: number | null;
  maximum: number | null;
  choices: string[] | null;
  secret: boolean;
  editable: boolean;
  show_when: { key: string; value: string } | null; // only relevant while that setting has that value
  source: "default" | "env" | "ui";
  configured: boolean;
  value: unknown;
  env_value: unknown;
  default: unknown;
}

/** GET /system/storage: where images are kept. */
export interface StorageStatus {
  backend: string;
  configured: boolean;
  counts: Record<string, number>;
  to_move: number;
}
export interface StorageTest {
  status: "ok" | "failed";
  backend: string;
  error: string | null;
}
/** One round of POST /system/storage/move. */
export interface StorageMove {
  moved: number;
  missing: number;
  failed: number;
  remaining: number;
  error: string | null;
}

export type HealthStatus = "ok" | "warn" | "error";

/** GET /system/health: what the System status panel shows. */
export interface InstanceHealth {
  database: HealthStatus;
  worker: { status: HealthStatus; last_beat_at: string | null; live: number };
  outbox: {
    status: HealthStatus;
    pending: number;
    held: number;
    failed_24h: number;
    oldest_due_seconds: number | null;
    recent_failures: {
      site: string;
      channel: string | null;
      provider: string | null;
      queued_at: string;
      attempts: number;
      error: string;
    }[];
  };
  redis: HealthStatus | null; // null: not configured
  inbound: { source: string; label: string; status: HealthStatus; last_ok_at: string | null; last_error_at: string | null; last_error: string | null; last_stored_at: string | null; counts: Partial<Record<"stored" | "unmatched" | "bounced" | "ignored", number>> }[];
  checklist: { id: "mail" | "public_url" | "worker" | "site" | "channel"; done: boolean }[];
}

export interface DayStats {
  day: string; // YYYY-MM-DD (UTC)
  accepted: number;
  quarantined: number;
  honeypot: number;
  duplicate: number;
  origin_denied: number;
  rate_limited: number;
  daily_limit: number;
  challenge_failed: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Access token lives in memory only; the refresh token is an httpOnly cookie.
let accessToken: string | null = null;
let onLoggedOut: () => void = () => {};
let refreshing: Promise<boolean> | null = null;
// Bumped whenever the token is set explicitly (sign-in, logout), so a refresh that started earlier
// (the page-load restore) can't land afterwards and replace the newer session with a stale one.
let session = 0;

function setToken(token: string | null) {
  session++;
  accessToken = token;
}

export function setLogoutHandler(fn: () => void) {
  onLoggedOut = fn;
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return res.statusText;
}

async function tokenRequest(path: string, init?: RequestInit): Promise<boolean> {
  const started = session;
  const res = await fetch(BASE + path, { method: "POST", credentials: "include", ...init });
  if (!res.ok) return false;
  const { access_token } = await res.json();
  if (session !== started) return false;
  accessToken = access_token;
  return true;
}

export function refresh(): Promise<boolean> {
  refreshing ??= tokenRequest("/auth/refresh").finally(() => (refreshing = null));
  return refreshing;
}

/** Returns an MFA token when a second step is needed; otherwise the session is already open. */
export async function login(email: string, password: string): Promise<string | null> {
  const res = await fetch(BASE + "/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  const body = await res.json();
  if (body.mfa_required) return body.mfa_token as string;
  setToken(body.access_token);
  return null;
}

export async function loginTotp(mfa_token: string, code: string) {
  const res = await fetch(BASE + "/auth/login/totp", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_token, code }),
  });
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  setToken((await res.json()).access_token);
}

/** Enabling or disabling TOTP signs out other sessions; this one gets a fresh token. */
export async function totpChange<T extends { access_token: string }>(path: string, body: unknown): Promise<T> {
  const r = await api<T>(path, json("POST", body));
  setToken(r.access_token);
  return r;
}

export async function changePassword(current_password: string, new_password: string) {
  // Other sessions are revoked server-side; this one gets a fresh token pair.
  const r = await api<{ access_token: string }>("/auth/me/password", json("POST", { current_password, new_password }));
  setToken(r.access_token);
}

export async function logout() {
  await fetch(BASE + "/auth/logout", { method: "POST", credentials: "include" }).catch(() => {});
  setToken(null);
}

async function request(path: string, init: RequestInit, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(BASE + path, { ...init, headers, credentials: "include" });
  if (res.status === 401 && retry) {
    if (await refresh()) return request(path, init, false);
    accessToken = null;
    onLoggedOut();
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await request(path, init);
  return res.status === 204 ? (undefined as T) : res.json();
}

/** Fetch a file with the session's credentials and hand it to the browser as a download. */
export async function download(path: string, fallbackName: string, init: RequestInit = {}) {
  const res = await request(path, init);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Fetch a file with the session's credentials, e.g. an image the browser could not request itself (no cookies). */
export async function fetchBlob(path: string): Promise<Blob> {
  return (await request(path, {})).blob();
}

export const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export type OutboxStatus = "pending" | "sending" | "sent" | "failed" | "held";
export interface JsonSchemaProp {
  type?: string;
  title?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
}
export interface ConfigSchema {
  properties?: Record<string, JsonSchemaProp>;
  required?: string[];
}
export interface ProviderInfo {
  key: string;
  label: string;
  configured: boolean;
  uses_recipients: boolean;
  signs: boolean;
  config_schema: ConfigSchema;
}
export interface VerifierInfo {
  key: string;
  label: string;
  config_schema: ConfigSchema;
}
export interface ChannelFilters {
  issue_types: string[]; // "(none)" stands for items without a type
  rating_min: number | null;
  rating_max: number | null;
  has_email: boolean | null;
  page_contains: string;
}
export interface Channel {
  id: string;
  provider: string;
  name: string;
  enabled: boolean;
  config: Record<string, unknown>;
  events: string[];
  min_role: Role;
  filters: ChannelFilters;
  extra_recipients: string[];
  has_secret: boolean;
  created_at: string;
}
export interface Delivery {
  id: string;
  channel_name: string | null;
  event_type: string;
  status: OutboxStatus;
  attempts: number;
  summary: boolean;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}

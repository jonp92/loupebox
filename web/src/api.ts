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
  sites_with_new: number;
  sites: DashboardSite[];
  recent_new: DashboardItem[];
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
  const res = await fetch(BASE + path, { method: "POST", credentials: "include", ...init });
  if (!res.ok) return false;
  accessToken = (await res.json()).access_token;
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
  accessToken = body.access_token;
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
  accessToken = (await res.json()).access_token;
}

/** Enabling or disabling TOTP signs out other sessions; this one gets a fresh token. */
export async function totpChange<T extends { access_token: string }>(path: string, body: unknown): Promise<T> {
  const r = await api<T>(path, json("POST", body));
  accessToken = r.access_token;
  return r;
}

export async function changePassword(current_password: string, new_password: string) {
  // Other sessions are revoked server-side; this one gets a fresh token pair.
  const r = await api<{ access_token: string }>("/auth/me/password", json("POST", { current_password, new_password }));
  accessToken = r.access_token;
}

export async function logout() {
  await fetch(BASE + "/auth/logout", { method: "POST", credentials: "include" }).catch(() => {});
  accessToken = null;
}

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(BASE + path, { ...init, headers, credentials: "include" });
  if (res.status === 401 && retry) {
    if (await refresh()) return api<T>(path, init, false);
    accessToken = null;
    onLoggedOut();
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res.status === 204 ? (undefined as T) : res.json();
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
  config_schema: ConfigSchema;
}
export interface VerifierInfo {
  key: string;
  label: string;
  config_schema: ConfigSchema;
}
export interface Channel {
  id: string;
  provider: string;
  name: string;
  enabled: boolean;
  config: Record<string, unknown>;
  events: string[];
  min_role: Role;
  extra_recipients: string[];
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

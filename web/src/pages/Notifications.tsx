import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  json,
  type Channel,
  type ChannelFilters,
  type Delivery,
  type ProviderInfo,
  type Role,
  type Site,
} from "../api";
import { SchemaFields } from "../components";
import { useConfirm } from "../confirm";
import { sendTest } from "../testSend";
import { useToast } from "../toast";
import { Badge } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";
import { Icon } from "../icons";
import { Sheet } from "../ui/Sheet";
import { Status, type StatusTone } from "../ui/Status";

const DELIVERY_TONE: Record<string, StatusTone> = { sent: "ok", failed: "danger" }; // held, pending and sending are muted

const ROLES: Role[] = ["viewer", "editor", "admin"];
// `machine` events only make sense for endpoints that feed other systems, not for email.
const EVENTS = [{ key: "feedback.created", label: "New feedback", machine: false }, { key: "feedback.replied", label: "A reply was sent", machine: true }];
const SPLIT = /[\s,;]+/;
const NO_TYPE = "(none)";
const NO_FILTERS: ChannelFilters = { issue_types: [], rating_min: null, rating_max: null, has_email: null, page_contains: "" };
const RATINGS = [1, 2, 3, 4, 5];

/** The filter in words, for the channel list. Empty when the channel hears about everything. */
function filterSummary(f: ChannelFilters): string {
  const parts = [];
  if (f.issue_types.length) parts.push(f.issue_types.map((t) => (t === NO_TYPE ? "no type" : t)).join(", "));
  if (f.rating_min || f.rating_max) {
    const [lo, hi] = [f.rating_min ?? 1, f.rating_max ?? 5];
    parts.push(lo === hi ? `rating ${lo}` : f.rating_max === null ? `rating ${lo}+` : f.rating_min === null ? `rating up to ${hi}` : `rating ${lo}–${hi}`);
  }
  if (f.has_email !== null) parts.push(f.has_email ? "left an email" : "no email");
  if (f.page_contains) parts.push(`page contains "${f.page_contains}"`);
  return parts.join(" · ");
}

const when = (iso: string) => new Date(iso).toLocaleString();

/** The signing secret is only returned when created or rotated, so this is the one chance to copy it. */
function SecretNotice({ name, secret, onClose }: { name: string; secret: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <section className="notice secret-notice" role="status">
      <h2>Signing secret for "{name}"</h2>
      <p>Copy it now: it won't be shown again. Your endpoint uses it to check that requests really come from Loupebox. If you lose it, rotate it.</p>
      <p><code className="secret">{secret}</code></p>
      <div className="row-actions">
        <button
          onClick={() => navigator.clipboard.writeText(secret).then(() => setCopied(true), () => setCopied(false))}
        >{copied ? "Copied" : "Copy"}</button>
        <button className="primary" onClick={onClose}>I've saved it</button>
      </div>
    </section>
  );
}

function ChannelForm({ siteId, providers, channel, onSaved, onCancel }: {
  siteId: string;
  providers: ProviderInfo[];
  channel?: Channel;
  onSaved: (created?: { name: string; secret: string }) => void;
  onCancel: () => void;
}) {
  const [provider, setProvider] = useState(channel?.provider ?? providers[0]?.key ?? "");
  const [name, setName] = useState(channel?.name ?? "");
  const [config, setConfig] = useState<Record<string, unknown>>(channel?.config ?? {});
  const [events, setEvents] = useState<string[]>(channel?.events ?? ["feedback.created"]);
  const [minRole, setMinRole] = useState<Role>(channel?.min_role ?? "admin");
  const [filters, setFilters] = useState<ChannelFilters>(channel?.filters ?? NO_FILTERS);
  const [seenTypes, setSeenTypes] = useState<string[]>([]);
  const [extra, setExtra] = useState((channel?.extra_recipients ?? []).join("\n"));
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ id: string }[]>(`/sites/${siteId}/feedback/issue-types`).then((r) => setSeenTypes(r.map((t) => t.id)), () => {});
  }, [siteId]);
  const setFilter = <K extends keyof ChannelFilters>(key: K, value: ChannelFilters[K]) => setFilters((f) => ({ ...f, [key]: value }));
  const typeChoices = [...new Set([...seenTypes, ...filters.issue_types.filter((t) => t !== NO_TYPE)])];
  const numberOrNull = (v: string) => (v === "" ? null : Number(v));

  const info = providers.find((p) => p.key === provider);
  const blocked = info !== undefined && !info.configured;
  const recipients = info?.uses_recipients ?? true;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const body = {
      name,
      config,
      events,
      min_role: minRole,
      filters: { ...filters, page_contains: filters.page_contains.trim() },
      enabled: enabled && !blocked,
      extra_recipients: extra.split(SPLIT).filter(Boolean),
    };
    try {
      const saved = await api<Channel & { secret?: string | null }>(
        `/sites/${siteId}/notifications${channel ? `/${channel.id}` : ""}`,
        json(channel ? "PATCH" : "POST", channel ? body : { ...body, provider }),
      );
      onSaved(saved.secret ? { name: saved.name, secret: saved.secret } : undefined);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="grid-2">
        <label>Provider
          <select value={provider} onChange={(e) => { setProvider(e.target.value); setConfig({}); }} disabled={!!channel}>
            {providers.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} placeholder="e.g. Team inbox" /></label>
      </div>
      {blocked && (
        <p className="error">{info.label} isn't configured on the server, so this channel can't be enabled yet. See the setup guide.</p>
      )}
      {info && <SchemaFields schema={info.config_schema} values={config} onChange={setConfig} />}
      <fieldset>
        <legend>Notify on</legend>
        {EVENTS.filter((ev) => !ev.machine || !recipients).map((ev) => (
          <label key={ev.key} className="inline">
            <input
              type="checkbox"
              checked={events.includes(ev.key)}
              onChange={(e) => setEvents(e.target.checked ? [...events, ev.key] : events.filter((x) => x !== ev.key))}
            /> {ev.label}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Only notify when</legend>
        <p className="hint muted">Leave everything empty to hear about every item. Several choices must all match.</p>
        {[...typeChoices, NO_TYPE].map((t) => (
          <label key={t} className="inline">
            <input
              type="checkbox"
              checked={filters.issue_types.includes(t)}
              onChange={(e) => setFilter("issue_types", e.target.checked ? [...filters.issue_types, t] : filters.issue_types.filter((x) => x !== t))}
            /> {t === NO_TYPE ? "No issue type" : `Type: ${t}`}
          </label>
        ))}
        <div className="grid-2">
          <label>Lowest rating
            <select value={filters.rating_min ?? ""} onChange={(e) => setFilter("rating_min", numberOrNull(e.target.value))}>
              <option value="">Any</option>
              {RATINGS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label>Highest rating
            <select value={filters.rating_max ?? ""} onChange={(e) => setFilter("rating_max", numberOrNull(e.target.value))}>
              <option value="">Any</option>
              {RATINGS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
        </div>
        <div className="grid-2">
          <label>Email address
            <select value={filters.has_email === null ? "" : String(filters.has_email)} onChange={(e) => setFilter("has_email", e.target.value === "" ? null : e.target.value === "true")}>
              <option value="">Either</option>
              <option value="true">Left one</option>
              <option value="false">Did not leave one</option>
            </select>
          </label>
          <label>Page address contains
            <input value={filters.page_contains} onChange={(e) => setFilter("page_contains", e.target.value)} maxLength={200} placeholder="e.g. /pricing" />
          </label>
        </div>
      </fieldset>
      {recipients && (
        <>
          <label>Send to members who are at least
            <select value={minRole} onChange={(e) => setMinRole(e.target.value as Role)}>
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
          <label>Extra recipients<small> (one per line, up to 20)</small>
            <textarea rows={3} value={extra} onChange={(e) => setExtra(e.target.value)} />
          </label>
        </>
      )}
      <label className="inline">
        <input type="checkbox" checked={enabled && !blocked} disabled={blocked} onChange={(e) => setEnabled(e.target.checked)} /> Enabled
      </label>
      <div className="row-actions">
        <button type="button" onClick={onCancel}>Cancel</button>
        <button className="primary" disabled={busy || !name}>{channel ? "Save" : "Add channel"}</button>
      </div>
    </form>
  );
}

export default function Notifications({ site }: { site: Site }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<{ name: string; secret: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, c, d] = await Promise.all([
        api<ProviderInfo[]>("/notifications/providers"),
        api<Channel[]>(`/sites/${site.id}/notifications`),
        api<Delivery[]>(`/sites/${site.id}/notifications/deliveries`),
      ]);
      setProviders(p);
      setChannels(c);
      setDeliveries(d);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [site.id]);
  useEffect(() => void load(), [load]);

  const info = (key: string) => providers.find((p) => p.key === key);
  const label = (key: string) => providers.find((p) => p.key === key)?.label ?? key;
  const configured = (key: string) => providers.find((p) => p.key === key)?.configured ?? false;

  async function test(c: Channel) {
    setTesting(c.id);
    await sendTest(`/sites/${site.id}/notifications/${c.id}/test`, toast);
    setTesting(null);
  }

  async function rotate(c: Channel) {
    const ok = await confirm({
      title: `Rotate the signing secret for "${c.name}"?`,
      message: "The current secret stops working immediately, so update your endpoint with the new one.",
      confirmLabel: "Rotate",
      danger: true,
    });
    if (!ok) return;
    await toast.attempt(
      api<{ secret: string }>(`/sites/${site.id}/notifications/${c.id}/rotate-secret`, { method: "POST" })
        .then((r) => setRevealed({ name: c.name, secret: r.secret })),
    );
  }

  async function remove(c: Channel) {
    if (!(await confirm({ title: `Delete the channel "${c.name}"?`, message: "Past deliveries stay in the log.", confirmLabel: "Delete", danger: true }))) return;
    await toast.attempt(api(`/sites/${site.id}/notifications/${c.id}`, { method: "DELETE" }), "Channel deleted");
    load();
  }

  const saved = (created?: { name: string; secret: string }) => {
    toast.success("Channel saved");
    setEditing(null);
    if (created) setRevealed(created);
    load();
  };
  const unconfigured = providers.filter((p) => !p.configured && channels.some((c) => c.provider === p.key));

  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      {unconfigured.map((p) => (
        <p key={p.key} className="error" role="alert">
          {p.label} isn't configured on the server. Channels using it won't send until the operator sets it up.
        </p>
      ))}

      {revealed && <SecretNotice {...revealed} onClose={() => setRevealed(null)} />}

      <div className="section-head">
        <h2>Channels <span className="count">{channels.length}</span></h2>
        <button className="primary" onClick={() => setEditing("new")} disabled={providers.length === 0}><Icon name="plus" size={18} />Add channel</button>
      </div>
      <Sheet open={editing !== null} title={editing === "new" ? "Add channel" : "Edit channel"} onClose={() => setEditing(null)}>
        <ChannelForm siteId={site.id} providers={providers} channel={channels.find((c) => c.id === editing)} onSaved={saved} onCancel={() => setEditing(null)} />
      </Sheet>
      <ul className="ruled">
        {channels.map((c) => (
          <li key={c.id} className="channel-row">
            <span className="ruled-main-col">
              <strong className="ruled-title">{c.name}</strong>
              <span className="channel-meta">
                <Badge>{label(c.provider)}</Badge>
                {info(c.provider)?.uses_recipients !== false && <Badge>{c.min_role}+</Badge>}
                {c.extra_recipients.length > 0 && <Badge>+{c.extra_recipients.length} extra</Badge>}
                <Status tone={c.enabled ? "ok" : "muted"}>{c.enabled ? "enabled" : "disabled"}</Status>
                {!configured(c.provider) && <Status tone="danger">not configured</Status>}
              </span>
              {filterSummary(c.filters) && <span className="muted check-detail">Only when: {filterSummary(c.filters)}</span>}
            </span>
            <span className="row-actions">
              <button onClick={() => test(c)} disabled={testing === c.id || !configured(c.provider)}>
                {testing === c.id ? "Sending…" : info(c.provider)?.uses_recipients === false ? "Send test" : "Send test to me"}
              </button>
              {info(c.provider)?.signs && <button onClick={() => rotate(c)}>Rotate secret</button>}
              <button onClick={() => setEditing(c.id)}>Edit</button>
              <button className="danger" onClick={() => remove(c)}>Delete</button>
            </span>
          </li>
        ))}
      </ul>
      {channels.length === 0 && <EmptyState>No channels yet. Add one to get emailed, or posted to a webhook, when feedback arrives.</EmptyState>}

      <div className="section-head"><h2>Recent deliveries <span className="count">{deliveries.length}</span></h2></div>
      {deliveries.length === 0 ? (
        <EmptyState>Nothing sent yet.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="viz-table log-table">
            <thead>
              <tr><th>Queued</th><th>Channel</th><th>Status</th><th>Tries</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {deliveries.map((d) => (
                <tr key={d.id}>
                  <td>{when(d.created_at)}</td>
                  <td>{d.channel_name ?? <span className="muted">deleted</span>}</td>
                  <td><Status tone={DELIVERY_TONE[d.status] ?? "muted"}>{d.status}</Status>{d.summary && <Badge>summary</Badge>}</td>
                  <td>{d.attempts}</td>
                  <td>{d.last_error ?? (d.sent_at ? `Sent ${when(d.sent_at)}` : "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted hint">
        Each email channel has an hourly limit. Anything beyond it is rolled into one summary email a few minutes later. Webhook channels send every event.
      </p>
    </>
  );
}

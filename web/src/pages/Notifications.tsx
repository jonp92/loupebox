import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  json,
  type Channel,
  type Delivery,
  type JsonSchemaProp,
  type ProviderInfo,
  type Role,
  type Site,
} from "../api";

const ROLES: Role[] = ["viewer", "editor", "admin"];
const EVENTS = [{ key: "feedback.created", label: "New feedback" }];
const SPLIT = /[\s,;]+/;

const when = (iso: string) => new Date(iso).toLocaleString();

/** One input per primitive property of the provider's config schema. */
function SchemaFields({ schema, values, onChange }: {
  schema: ProviderInfo["config_schema"];
  values: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const props = Object.entries(schema.properties ?? {});
  if (props.length === 0) return null;
  const set = (k: string, v: unknown) => onChange({ ...values, [k]: v });

  return (
    <>
      {props.map(([key, p]: [string, JsonSchemaProp]) => {
        const label = p.title ?? key;
        const value = values[key] ?? p.default ?? "";
        if (p.type === "boolean") {
          return (
            <label key={key} className="inline">
              <input type="checkbox" checked={Boolean(value)} onChange={(e) => set(key, e.target.checked)} /> {label}
            </label>
          );
        }
        if (p.enum) {
          return (
            <label key={key}>{label}
              <select value={String(value)} onChange={(e) => set(key, e.target.value)}>
                {p.enum.map((o) => <option key={o}>{o}</option>)}
              </select>
            </label>
          );
        }
        const numeric = p.type === "integer" || p.type === "number";
        return (
          <label key={key}>{label}
            <input
              type={numeric ? "number" : "text"}
              value={String(value)}
              required={schema.required?.includes(key)}
              onChange={(e) => set(key, numeric && e.target.value !== "" ? Number(e.target.value) : e.target.value)}
            />
            {p.description && <small className="muted"> {p.description}</small>}
          </label>
        );
      })}
    </>
  );
}

function ChannelForm({ siteId, providers, channel, onSaved, onCancel }: {
  siteId: string;
  providers: ProviderInfo[];
  channel?: Channel;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [provider, setProvider] = useState(channel?.provider ?? providers[0]?.key ?? "");
  const [name, setName] = useState(channel?.name ?? "");
  const [config, setConfig] = useState<Record<string, unknown>>(channel?.config ?? {});
  const [events, setEvents] = useState<string[]>(channel?.events ?? ["feedback.created"]);
  const [minRole, setMinRole] = useState<Role>(channel?.min_role ?? "admin");
  const [extra, setExtra] = useState((channel?.extra_recipients ?? []).join("\n"));
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const info = providers.find((p) => p.key === provider);
  const blocked = info !== undefined && !info.configured;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const body = {
      name,
      config,
      events,
      min_role: minRole,
      enabled: enabled && !blocked,
      extra_recipients: extra.split(SPLIT).filter(Boolean),
    };
    try {
      await api(
        `/sites/${siteId}/notifications${channel ? `/${channel.id}` : ""}`,
        json(channel ? "PATCH" : "POST", channel ? body : { ...body, provider }),
      );
      onSaved();
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
        {EVENTS.map((ev) => (
          <label key={ev.key} className="inline">
            <input
              type="checkbox"
              checked={events.includes(ev.key)}
              onChange={(e) => setEvents(e.target.checked ? [...events, ev.key] : events.filter((x) => x !== ev.key))}
            /> {ev.label}
          </label>
        ))}
      </fieldset>
      <label>Send to members who are at least
        <select value={minRole} onChange={(e) => setMinRole(e.target.value as Role)}>
          {ROLES.map((r) => <option key={r}>{r}</option>)}
        </select>
      </label>
      <label>Extra recipients<small> (one per line, up to 20)</small>
        <textarea rows={3} value={extra} onChange={(e) => setExtra(e.target.value)} />
      </label>
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
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testMsg, setTestMsg] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [error, setError] = useState("");

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

  const label = (key: string) => providers.find((p) => p.key === key)?.label ?? key;
  const configured = (key: string) => providers.find((p) => p.key === key)?.configured ?? false;

  async function test(c: Channel) {
    setTesting(c.id);
    try {
      const r = await api<{ status: string; error: string | null; to: string }>(
        `/sites/${site.id}/notifications/${c.id}/test`, { method: "POST" },
      );
      const text = r.status === "sent" ? `Test sent to ${r.to}` : `Test ${r.status}: ${r.error ?? "unknown error"}`;
      setTestMsg((m) => ({ ...m, [c.id]: { ok: r.status === "sent", text } }));
    } catch (e) {
      setTestMsg((m) => ({ ...m, [c.id]: { ok: false, text: (e as Error).message } }));
    } finally {
      setTesting(null);
    }
  }

  async function remove(c: Channel) {
    if (!confirm(`Delete the channel "${c.name}"? Past deliveries stay in the log.`)) return;
    await api(`/sites/${site.id}/notifications/${c.id}`, { method: "DELETE" }).catch((e) => setError(e.message));
    load();
  }

  const saved = () => { setEditing(null); load(); };
  const unconfigured = providers.filter((p) => !p.configured && channels.some((c) => c.provider === p.key));

  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      {unconfigured.map((p) => (
        <p key={p.key} className="error" role="alert">
          {p.label} isn't configured on the server. Channels using it won't send until the operator sets it up.
        </p>
      ))}

      <h2 className="section">Channels <span className="count">{channels.length}</span></h2>
      <ul className="list">
        {channels.map((c) => (
          <li key={c.id} className={editing === c.id ? "editing" : "channel"}>
            {editing === c.id ? (
              <ChannelForm siteId={site.id} providers={providers} channel={c} onSaved={saved} onCancel={() => setEditing(null)} />
            ) : (
              <>
                <span className="grow stack">
                  <strong>{c.name}</strong>
                  <span className="origins">
                    <span className="badge">{label(c.provider)}</span>
                    <span className={`badge ${c.enabled ? "sent" : ""}`}>{c.enabled ? "enabled" : "disabled"}</span>
                    {!configured(c.provider) && <span className="badge failed">not configured</span>}
                    <span className="badge">{c.min_role}+</span>
                    {c.extra_recipients.length > 0 && <span className="badge">+{c.extra_recipients.length} extra</span>}
                  </span>
                  {testMsg[c.id] && (
                    <span className={testMsg[c.id].ok ? "success" : "error"} role="status">{testMsg[c.id].text}</span>
                  )}
                </span>
                <button onClick={() => test(c)} disabled={testing === c.id || !configured(c.provider)}>
                  {testing === c.id ? "Sending…" : "Send test to me"}
                </button>
                <button onClick={() => setEditing(c.id)}>Edit</button>
                <button className="danger" onClick={() => remove(c)}>Delete</button>
              </>
            )}
          </li>
        ))}
        {channels.length === 0 && <li className="muted">No channels yet. Add one to get emailed when feedback arrives.</li>}
      </ul>

      {editing === "new" ? (
        <section className="card">
          <h2>Add channel</h2>
          <ChannelForm siteId={site.id} providers={providers} onSaved={saved} onCancel={() => setEditing(null)} />
        </section>
      ) : (
        <p><button className="primary" onClick={() => setEditing("new")} disabled={providers.length === 0}>Add channel</button></p>
      )}

      <h2 className="section">Recent deliveries <span className="count">{deliveries.length}</span></h2>
      {deliveries.length === 0 ? (
        <p className="muted">Nothing sent yet.</p>
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
                  <td><span className={`badge ${d.status}`}>{d.status}</span>{d.summary && <span className="badge"> summary</span>}</td>
                  <td>{d.attempts}</td>
                  <td>{d.last_error ?? (d.sent_at ? `Sent ${when(d.sent_at)}` : "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted hint">
        Each channel has an hourly email limit. Anything beyond it is rolled into one summary email a few minutes later.
      </p>
    </>
  );
}

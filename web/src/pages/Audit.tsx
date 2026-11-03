import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, type AuditEvent } from "../api";
import { useAuth } from "../auth";

const PAGE = 50;
const GROUPS = [
  ["", "All activity"],
  ["user", "Users"],
  ["site", "Sites"],
  ["member", "Site members"],
  ["channel", "Notification channels"],
  ["feedback", "Feedback"],
  ["auth", "Own account"],
] as const;

const when = (iso: string) => new Date(iso).toLocaleString();
const isChange = (v: unknown): v is { from: unknown; to: unknown } =>
  typeof v === "object" && v !== null && "from" in v && "to" in v;
const show = (v: unknown) => (typeof v === "string" ? (v === "" ? "(empty)" : v) : JSON.stringify(v));

/** One line per changed field. Values are rendered as text, never as HTML. */
function Details({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details);
  if (entries.length === 0) return null;
  return (
    <details className="audit-details">
      <summary>Details</summary>
      <dl>
        {entries.map(([key, v]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{isChange(v) ? <>{show(v.from)} <span aria-label="to">→</span> {show(v.to)}</> : show(v)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export default function Audit() {
  const { me } = useAuth();
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [group, setGroup] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (group) params.set("group", group);
    if (q) params.set("q", q);
    api<{ items: AuditEvent[]; total: number }>(`/audit?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [offset, group, q]);
  useEffect(load, [load]);

  if (!me?.is_superadmin) return <Navigate to="/" replace />;

  return (
    <>
      <div className="page-head"><h1>Audit log</h1><span className="count">{total}</span></div>
      <p className="muted">Administrative changes, newest first. Passwords, keys and message contents are never recorded.</p>
      <div className="toolbar">
        <input
          placeholder="Search summary or admin email"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
        />
        <select value={group} onChange={(e) => { setGroup(e.target.value); setOffset(0); }} aria-label="Type of change">
          {GROUPS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!error && items.length === 0 && <p className="empty-state">No events found.</p>}
      <ul className="list audit">
        {items.map((e) => (
          <li key={e.id}>
            <span className="grow stack">
              <strong>{e.summary}</strong>
              <span className="muted">
                {e.actor_email} · {when(e.created_at)}
                {e.site_name && <> · {e.site_name}</>}
              </span>
              <Details details={e.details} />
            </span>
            <span className="badge">{e.action}</span>
          </li>
        ))}
      </ul>
      <div className="toolbar">
        <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Previous</button>
        <span className="muted">{total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
        <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
      </div>
    </>
  );
}

import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, json, type Dashboard as DashboardData } from "../api";
import { useAuth } from "../auth";

export default function Dashboard() {
  const { me } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  const load = () => api<DashboardData>("/dashboard").then(setData).catch((e) => setError(e.message));
  useEffect(() => void load(), []);

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const origins = String(data.get("origins")).split(/[\s,]+/).filter(Boolean);
    try {
      await api("/sites", json("POST", { name: data.get("name"), allowed_origins: origins }));
      form.reset();
      setError("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function markRead(siteId: string, id: string) {
    await api(`/sites/${siteId}/feedback/${id}`, json("PATCH", { status: "read" })).catch((e) => setError(e.message));
    load();
  }

  const sites = data?.sites;
  const role = (siteId: string) => sites?.find((s) => s.id === siteId)?.my_role;

  return (
    <>
      <div className="page-head"><h1>Dashboard</h1></div>
      {error && <p className="error">{error}</p>}
      {data && (
        <div className="stats">
          <div className="stat"><strong>{data.new_total}</strong><span className="muted">Unread</span></div>
          <div className="stat"><strong>{data.new_24h}</strong><span className="muted">Unread, last 24h</span></div>
          <div className="stat"><strong>{data.sites_with_new}</strong><span className="muted">Sites with unread</span></div>
        </div>
      )}
      {data && data.new_total > 0 && (
        <>
          <h2 className="section">Latest unread</h2>
          <ul className="list unread">
            {data.recent_new.map((f) => {
              const canEdit = role(f.site_id) !== "viewer";
              return (
                <li key={f.id}>
                  <Link to={`/sites/${f.site_id}`} className="grow site-link">
                    <span className="muted">{f.site_name} · {new Date(f.created_at).toLocaleString()}</span>
                    {/* Rendered as text by React; never as HTML. */}
                    <span className="excerpt">{f.message}</span>
                  </Link>
                  {canEdit && <button onClick={() => markRead(f.site_id, f.id)}>Mark read</button>}
                </li>
              );
            })}
          </ul>
          {data.new_total > data.recent_new.length && (
            <p className="muted">Showing {data.recent_new.length} of {data.new_total}. Open a site to see the rest.</p>
          )}
        </>
      )}
      {data && data.new_total === 0 && sites && sites.length > 0 && <p className="empty-state">All caught up. No unread feedback.</p>}
      <h2 className="section">Sites</h2>
      {sites?.length === 0 && <p className="empty-state">You don't have access to any sites yet. Ask an admin to add you.</p>}
      <ul className="list">
        {sites?.map((s) => (
          <li key={s.id}>
            <Link to={`/sites/${s.id}`} className="grow site-link">
              <strong>{s.name}</strong>
              <span className="origins">
                {s.allowed_origins.length
                  ? s.allowed_origins.map((o) => <span key={o} className="origin">{o}</span>)
                  : <span className="muted">No allowed origins yet</span>}
              </span>
            </Link>
            {s.new_count > 0 && <span className="badge new">{s.new_count} new</span>}
            <span className="badge">{s.my_role}</span>
            {!s.is_active && <span className="badge warn">disabled</span>}
          </li>
        ))}
      </ul>
      {me?.is_superadmin && (
        <form className="card" onSubmit={create}>
          <h2>New site</h2>
          <label>Name<input name="name" required maxLength={120} /></label>
          <label>
            Allowed origins <small>(space or comma separated, e.g. https://example.com)</small>
            <input name="origins" />
          </label>
          <button className="primary">Create site</button>
        </form>
      )}
    </>
  );
}

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, json, type Dashboard as DashboardData } from "../api";

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  const load = () => api<DashboardData>("/dashboard").then(setData).catch((e) => setError(e.message));
  useEffect(() => void load(), []);


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
      {data && data.assigned_total > 0 && (
        <>
          <h2 className="section">Assigned to you <span className="count">{data.assigned_total}</span></h2>
          <ul className="list unread">
            {data.assigned.map((f) => (
              <li key={f.id}>
                <Link to={`/sites/${f.site_id}/feedback/${f.id}`} className="grow site-link">
                  <span className="muted">{f.site_name} · {f.status} · {new Date(f.created_at).toLocaleString()}</span>
                  {/* Rendered as text by React; never as HTML. */}
                  <span className="excerpt">{f.message}</span>
                </Link>
              </li>
            ))}
          </ul>
          {data.assigned_total > data.assigned.length && (
            <p className="muted">Showing {data.assigned.length} of {data.assigned_total}. Open a site and use "Assigned to me" to see the rest.</p>
          )}
        </>
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
      {sites?.length === 0 && <p className="empty-state">You don't have access to any sites yet. Ask an admin to add you.</p>}
      {data && data.new_total === 0 && sites && sites.length > 0 && <p className="empty-state">All caught up. No unread feedback.</p>}
    </>
  );
}

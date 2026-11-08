import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { hasInbox, useAuth } from "../auth";
import { api, json, type Dashboard as DashboardData } from "../api";
import { Bar, Placeholder } from "../Skeleton";
import { useToast } from "../toast";
import { EmptyState } from "../ui/EmptyState";
import { Medallion } from "../ui/Medallion";
import { Status } from "../ui/Status";
import { Icon } from "../icons";

export default function Dashboard() {
  const toast = useToast();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  const load = () => api<DashboardData>("/dashboard").then(setData).catch((e) => setError(e.message));
  useEffect(() => void load(), []);


  async function markRead(siteId: string, id: string) {
    await toast.attempt(api(`/sites/${siteId}/feedback/${id}`, json("PATCH", { status: "read" })));
    load();
  }

  const sites = data?.sites;
  const inbox = hasInbox(useAuth().me);
  const role = (siteId: string) => sites?.find((s) => s.id === siteId)?.my_role;

  const stats: [string, number][] = data ? [["Unread", data.new_total], ["Unread, last 24h", data.new_24h], ["Sites with unread", data.sites_with_new]] : [];
  const caughtUp = data && data.new_total === 0 && sites && sites.length > 0;

  return (
    <>
      <div className="page-head"><h1>Dashboard</h1></div>
      {error && <p className="error">{error}</p>}
      {!data && !error && (
        <Placeholder label="Loading the dashboard">
          <div className="stat-band">{[0, 1, 2, 3].map((i) => <div key={i} className="ph"><Bar w="6rem" h=".8rem" /><Bar w="3rem" h="2rem" /></div>)}</div>
        </Placeholder>
      )}
      {data && (
        <>
          <div className="stat-band">
            <div className="stat-received">
              <Medallion count={data.received_total} label="received, excluding spam" />
              <span className="stat-label">Received<small>excl. spam</small></span>
            </div>
            <dl className="stat-cells">
              {stats.map(([label, n]) => <div key={label}><dt>{label}</dt><dd>{n.toLocaleString()}</dd></div>)}
            </dl>
          </div>
          {caughtUp && <EmptyState title="All caught up">No unread feedback.</EmptyState>}
        </>
      )}
      {data && data.assigned_total > 0 && (
        <>
          <h2 className="section-label">Assigned to you <span className="count">{data.assigned_total}</span></h2>
          <ul className="ruled">
            {data.assigned.map((f) => (
              <li key={f.id}>
                <Link to={`/sites/${f.site_id}/feedback/${f.id}`} className="ruled-link feedback-link">
                  <span className="meta">{f.site_name} · {f.status} · {new Date(f.created_at).toLocaleString()}</span>
                  {/* Rendered as text by React; never as HTML. */}
                  <span className="excerpt">{f.message}</span>
                </Link>
              </li>
            ))}
          </ul>
          {data.assigned_total > data.assigned.length && (
            <p className="muted">
              Showing {data.assigned.length} of {data.assigned_total}.{" "}
              {inbox ? <Link to="/inbox?assignee=me">See all in the inbox</Link> : 'Open a site and use "My work" to see the rest.'}
            </p>
          )}
        </>
      )}
      {data && data.new_total > 0 && (
        <>
          <h2 className="section-label">Unread by site</h2>
          <ul className="ruled">
            {sites?.filter((s) => s.new_count > 0).map((s) => (
              <li key={s.id}>
                <Link to={`/sites/${s.id}?status=new`} className="ruled-link">
                  <strong className="ruled-title">{s.name}</strong>
                  <span className="ruled-side"><Status tone="unread">{s.new_count} new</Status><Icon name="chevron" size={18} /></span>
                </Link>
              </li>
            ))}
          </ul>
          <h2 className="section-label">Latest unread</h2>
          <ul className="ruled">
            {data.recent_new.map((f) => {
              const canEdit = role(f.site_id) !== "viewer";
              return (
                <li key={f.id} className="ruled-row ruled-unread">
                  <Link to={`/sites/${f.site_id}/feedback/${f.id}`} className="ruled-link feedback-link">
                    <span className="meta">{f.site_name} · {new Date(f.created_at).toLocaleString()}</span>
                    {/* Rendered as text by React; never as HTML. */}
                    <span className="excerpt">{f.message}</span>
                  </Link>
                  {canEdit && <button onClick={() => markRead(f.site_id, f.id)}>Mark read</button>}
                </li>
              );
            })}
          </ul>
          {data.new_total > data.recent_new.length && (
            <p className="muted">
              Showing {data.recent_new.length} of {data.new_total}.{" "}
              {inbox ? <Link to="/inbox?status=new">See all unread in the inbox</Link> : "Open a site to see the rest."}
            </p>
          )}
        </>
      )}
      {sites?.length === 0 && <EmptyState>You don't have access to any sites yet. Ask an admin to add you.</EmptyState>}
    </>
  );
}

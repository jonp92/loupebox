import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, json, type Dashboard } from "../api";
import { soleSiteId, useAuth } from "../auth";
import { useToast } from "../toast";
import { Bar, Placeholder } from "../Skeleton";
import { Badge } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";
import { Sheet } from "../ui/Sheet";
import { Status } from "../ui/Status";
import { Icon } from "../icons";

export default function Sites() {
  const { me } = useAuth();
  const toast = useToast();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => api<Dashboard>("/dashboard").then(setData).catch((e) => setError(e.message));
  useEffect(() => void load(), []);
  const sites = data?.sites;

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const origins = String(data.get("origins")).split(/[\s,]+/).filter(Boolean);
    if (!(await toast.attempt(api("/sites", json("POST", { name: data.get("name"), allowed_origins: origins })), "Site created"))) return;
    setCreating(false);
    load();
  }

  const sole = soleSiteId(me);
  if (sole) return <Navigate to={`/sites/${sole}`} replace />;

  return (
    <>
      <div className="page-head">
        <h1>Sites</h1>
        {me?.is_superadmin && <button className="primary grow-end" onClick={() => setCreating(true)}><Icon name="plus" size={18} />New site</button>}
      </div>
      {error && <p className="error">{error}</p>}
      {!data && !error && (
        <Placeholder label="Loading sites">
          <ul className="ruled">
            {[0, 1, 2].map((i) => <li key={i} className="ph"><Bar w="10rem" /><Bar w="16rem" h=".8rem" /></li>)}
          </ul>
        </Placeholder>
      )}
      {sites?.length === 0 && <EmptyState>You don't have access to any sites yet. Ask an admin to add you.</EmptyState>}
      {sites && sites.length > 0 && (
        <ul className="ruled">
          {sites.map((s) => (
            <li key={s.id}>
              <Link to={`/sites/${s.id}`} className="ruled-link">
                <span className="ruled-main">
                  <strong className="ruled-title">{s.name}</strong>
                  {s.allowed_origins.length
                    ? s.allowed_origins.map((o) => <Origin key={o} url={o} />)
                    : <span className="muted">No allowed origins yet</span>}
                </span>
                <span className="ruled-side">
                  {s.new_count > 0 && <Status tone="unread">{s.new_count} new</Status>}
                  {!s.is_active && <Status tone="danger">Disabled</Status>}
                  <Badge>{s.my_role}</Badge>
                  <Icon name="chevron" size={18} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Sheet open={creating} title="New site" onClose={() => setCreating(false)}>
        <form onSubmit={create}>
          <label>Name<input name="name" required maxLength={120} /></label>
          <label>
            Allowed origins
            <input name="origins" placeholder="https://example.com" aria-describedby="origins-hint" className="mono" />
          </label>
          <p id="origins-hint" className="hint muted">Separate with spaces or commas.</p>
          <button className="primary block">Create site</button>
          <button type="button" className="plain block" onClick={() => setCreating(false)}>Cancel</button>
        </form>
      </Sheet>
    </>
  );
}

/** An origin on one mono line: the scheme dimmed, the host bright. */
function Origin({ url }: { url: string }) {
  const [, scheme = "", host = url] = url.match(/^(https?:\/\/)(.*)$/) ?? [];
  return <span className="origin-line"><span className="scheme">{scheme}</span>{host}</span>;
}

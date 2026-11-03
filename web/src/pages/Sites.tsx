import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, json, type Dashboard } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../toast";

export default function Sites() {
  const { me } = useAuth();
  const toast = useToast();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  const load = () => api<Dashboard>("/dashboard").then(setData).catch((e) => setError(e.message));
  useEffect(() => void load(), []);
  const sites = data?.sites;

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const origins = String(data.get("origins")).split(/[\s,]+/).filter(Boolean);
    if (!(await toast.attempt(api("/sites", json("POST", { name: data.get("name"), allowed_origins: origins })), "Site created"))) return;
    form.reset();
    load();
  }

  return (
    <>
      <div className="page-head"><h1>Sites</h1></div>
      {error && <p className="error">{error}</p>}
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

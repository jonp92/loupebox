import { useCallback, useEffect, useState } from "react";
import { api, json, type Feedback, type Site, type Status } from "../api";

const PAGE = 25;
const STATUSES: Status[] = ["new", "read", "archived", "spam"];

function safeHref(url: string | null): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}

export default function FeedbackList({ site }: { site: Site }) {
  const [items, setItems] = useState<Feedback[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const canEdit = site.my_role === "editor" || site.my_role === "admin";
  const canDelete = site.my_role === "admin";

  const load = useCallback(() => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    api<{ items: Feedback[]; total: number }>(`/sites/${site.id}/feedback?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [site.id, offset, status, q]);
  useEffect(load, [load]);

  async function setItemStatus(id: string, next: Status) {
    await api(`/sites/${site.id}/feedback/${id}`, json("PATCH", { status: next })).catch((e) => setError(e.message));
    load();
  }
  async function remove(id: string) {
    if (!confirm("Delete this feedback permanently?")) return;
    await api(`/sites/${site.id}/feedback/${id}`, { method: "DELETE" }).catch((e) => setError(e.message));
    load();
  }

  return (
    <>
      <div className="toolbar">
        <input
          placeholder="Search message, name, email"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
        />
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">All (excl. spam)</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="empty-state">No feedback found.</p>}
      {items.map((f) => {
        const href = safeHref(f.page_url);
        return (
          <article key={f.id} className={`card fb ${f.status}`}>
            <header>
              <span className={`badge ${f.status}`}>{f.status}</span>
              {f.rating && <span className="stars" title={`${f.rating} / 5`}>{"★".repeat(f.rating)}<span className="dim">{"★".repeat(5 - f.rating)}</span></span>}
              <span className="muted grow-end">{new Date(f.created_at).toLocaleString()}</span>
            </header>
            {/* Rendered as text by React; never as HTML. */}
            <p className="message">{f.message}</p>
            <p className="muted">
              {[f.name, f.email].filter(Boolean).join(" · ")}
              {href && <> · <a href={href} target="_blank" rel="noopener noreferrer">{href}</a></>}
            </p>
            {Object.keys(f.metadata).length > 0 && <pre>{JSON.stringify(f.metadata, null, 2)}</pre>}
            {canEdit && (
              <div className="actions">
                {STATUSES.filter((s) => s !== f.status).map((s) => (
                  <button key={s} onClick={() => setItemStatus(f.id, s)}>Mark {s}</button>
                ))}
                {canDelete && <button className="danger" onClick={() => remove(f.id)}>Delete</button>}
              </div>
            )}
          </article>
        );
      })}
      <div className="toolbar">
        <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Previous</button>
        <span className="muted">{total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
        <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
      </div>
    </>
  );
}

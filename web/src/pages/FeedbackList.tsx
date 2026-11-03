import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download, json, type Feedback, type Site, type Status } from "../api";
import { useConfirm } from "../confirm";

const PAGE = 25;
const STATUSES: Status[] = ["new", "read", "archived", "spam"];

/** The widget's badge ids are plain slugs; anything else in metadata is not shown as a badge. */
const ISSUE_TYPE = /^[a-z0-9_-]{1,32}$/;
const label = (id: string) => (id.replace(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase()));

function safeHref(url: string | null): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}

export default function FeedbackList({ site }: { site: Site }) {
  const confirm = useConfirm();
  const { feedbackId } = useParams();
  const navigate = useNavigate();
  const [items, setItems] = useState<Feedback[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [issueType, setIssueType] = useState("");
  const [issueTypes, setIssueTypes] = useState<{ id: string; count: number }[]>([]);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const canEdit = site.my_role === "editor" || site.my_role === "admin";
  const canDelete = site.my_role === "admin";

  const load = useCallback(() => {
    if (feedbackId) {
      api<Feedback>(`/sites/${site.id}/feedback/${feedbackId}`)
        .then((f) => {
          setItems([f]);
          setTotal(1);
          setError("");
        })
        .catch((e) => { setItems([]); setError(e.message); });
      return;
    }
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    if (issueType) params.set("issue_type", issueType);
    api<{ items: Feedback[]; total: number }>(`/sites/${site.id}/feedback?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [site.id, feedbackId, offset, status, q, issueType]);
  useEffect(load, [load]);
  // The kinds of feedback visitors have tagged (from the widget's badges), for the filter.
  useEffect(() => {
    api<{ id: string; count: number }[]>(`/sites/${site.id}/feedback/issue-types`).then(setIssueTypes, () => setIssueTypes([]));
  }, [site.id]);

  async function setItemStatus(id: string, next: Status) {
    await api(`/sites/${site.id}/feedback/${id}`, json("PATCH", { status: next })).catch((e) => setError(e.message));
    load();
  }
  async function exportCsv() {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    if (issueType) params.set("issue_type", issueType);
    setExporting(true);
    try {
      await download(`/sites/${site.id}/feedback/export.csv?${params}`, "feedback.csv");
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }
  async function remove(id: string) {
    if (!(await confirm({ title: "Delete this feedback?", message: "This cannot be undone.", confirmLabel: "Delete", danger: true }))) return;
    await api(`/sites/${site.id}/feedback/${id}`, { method: "DELETE" }).catch((e) => setError(e.message));
    if (feedbackId) navigate(`/sites/${site.id}`);
    else load();
  }

  return (
    <>
      {feedbackId && <p><Link to={`/sites/${site.id}`} className="back">← All feedback</Link></p>}
      {!feedbackId && <div className="toolbar">
        <input
          placeholder="Search message, name, email"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
        />
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">All (excl. spam)</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        {issueTypes.length > 0 && (
          <select value={issueType} onChange={(e) => { setIssueType(e.target.value); setOffset(0); }} aria-label="Type of feedback">
            <option value="">All types</option>
            {issueTypes.map((t) => <option key={t.id} value={t.id}>{label(t.id)} ({t.count})</option>)}
          </select>
        )}
        <button onClick={exportCsv} disabled={exporting || total === 0} title="Download what the search and status filter show, as CSV">
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>}
      {error && <p className="error">{error}</p>}
      {items.length === 0 && !error && <p className="empty-state">No feedback found.</p>}
      {items.map((f) => {
        const href = safeHref(f.page_url);
        return (
          <article key={f.id} className={`card fb ${f.status}`}>
            <header>
              <span className={`badge ${f.status}`}>{f.status}</span>
              {typeof f.metadata.issue_type === "string" && ISSUE_TYPE.test(f.metadata.issue_type) && (
                <span className="badge kind" data-kind={f.metadata.issue_type} title="Type chosen by the visitor">{label(f.metadata.issue_type)}</span>
              )}
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
      {!feedbackId && <div className="toolbar">
        <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Previous</button>
        <span className="muted">{total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
        <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
      </div>}
    </>
  );
}

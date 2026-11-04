import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, download, json, type Feedback, type Site, type Status } from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";
import {
  FeedbackBadges, TAG_PATTERN, ago, below, label, personName, recentAssignees, slug, useAssigneePicker, useContextMenu, type MenuItem,
} from "../triage";

const PAGE = 25;
const STATUSES: Status[] = ["new", "read", "archived", "spam"];

export default function FeedbackList({ site }: { site: Site }) {
  const confirm = useConfirm();
  const toast = useToast();
  const { me } = useAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState<Feedback[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [issueType, setIssueType] = useState("");
  const [issueTypes, setIssueTypes] = useState<{ id: string; count: number }[]>([]);
  const [rating, setRating] = useState("");
  const [hasEmail, setHasEmail] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [assignee, setAssignee] = useState("");
  const [tag, setTag] = useState("");
  const picker = useAssigneePicker(site.id);
  const [assigneeLabel, setAssigneeLabel] = useState(""); // who a per-person filter is for
  const [counts, setCounts] = useState({ mine: 0, unassigned: 0 });
  const ctx = useContextMenu();
  const [siteTags, setSiteTags] = useState<{ tag: string; count: number }[]>([]);
  const [bulkTag, setBulkTag] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false); // small screens only; wide ones always show the filters
  const [tagging, setTagging] = useState(false);
  const canEdit = site.my_role === "editor" || site.my_role === "admin";
  const canDelete = site.my_role === "admin";
  // Only editors and admins hold assignments, and a superadmin who is not a member cannot.
  const canBeAssigned = Boolean(me?.memberships.some((m) => m.site_id === site.id && m.role !== "viewer"));

  /** The list's filters as query params; the CSV export takes the same ones. */
  const filterParams = useCallback(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    if (issueType) params.set("issue_type", issueType);
    if (rating) params.set("rating", rating);
    if (hasEmail) params.set("has_email", hasEmail);
    if (from) params.set("created_from", from);
    if (to) params.set("created_to", to);
    if (assignee) params.set("assignee", assignee);
    if (tag) params.set("tag", tag);
    return params;
  }, [status, q, issueType, rating, hasEmail, from, to, assignee, tag]);

  const load = useCallback(() => {
    const params = filterParams();
    params.set("limit", String(PAGE));
    params.set("offset", String(offset));
    api<{ items: Feedback[]; total: number }>(`/sites/${site.id}/feedback?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setSelected(new Set()); // a new page or filter never keeps a hidden selection
        setError("");
      })
      .catch((e) => setError(e.message));
    api<typeof counts>(`/sites/${site.id}/feedback/counts`).then(setCounts, () => undefined);
  }, [site.id, offset, filterParams]);
  useEffect(load, [load]);
  // The kinds of feedback visitors have tagged (from the widget's badges), for the filter.
  useEffect(() => {
    api<{ id: string; count: number }[]>(`/sites/${site.id}/feedback/issue-types`).then(setIssueTypes, () => setIssueTypes([]));
  }, [site.id]);
  const loadTags = useCallback(() => {
    api<{ tag: string; count: number }[]>(`/sites/${site.id}/feedback/tags`).then(setSiteTags, () => setSiteTags([]));
  }, [site.id]);
  useEffect(loadTags, [loadTags]);
  /** Change one item (status, assignee or tags) and reload. */
  async function patchItem(id: string, body: Partial<{ status: Status; assignee_id: string | null; tags: string[] }>) {
    await toast.attempt(api(`/sites/${site.id}/feedback/${id}`, json("PATCH", body)));
    load();
    if (body.tags) loadTags();
  }
  const setItemStatus = (id: string, next: Status) => patchItem(id, { status: next });
  async function exportCsv() {
    const params = filterParams();
    setExporting(true);
    await toast.attempt(download(`/sites/${site.id}/feedback/export.csv?${params}`, "feedback.csv"), "Export downloaded");
    setExporting(false);
  }
  function toggle(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }
  const allSelected = items.length > 0 && items.every((f) => selected.has(f.id));
  type BulkBody =
    | { action: "set_status"; status: Status }
    | { action: "assign"; assignee_id: string | null }
    | { action: "add_tag" | "remove_tag"; tag: string }
    | { action: "delete" };
  async function bulk(body: BulkBody) {
    if (body.action === "delete" && !(await confirm({
      title: `Delete ${selected.size} feedback item${selected.size === 1 ? "" : "s"}?`,
      message: "This cannot be undone.", confirmLabel: "Delete", danger: true,
    }))) return;
    await toast.attempt(
      api<{ affected: number; skipped: number }>(`/sites/${site.id}/feedback/bulk`, json("POST", { ids: [...selected], ...body }))
        .then((r) => toast.success(`${r.affected} item${r.affected === 1 ? "" : "s"} updated${r.skipped ? `, ${r.skipped} skipped` : ""}`)),
    );
    load();
    loadTags();
  }
  function bulkAddTag() {
    const t = slug(bulkTag);
    if (!TAG_PATTERN.test(t)) return toast.error("Tags are 1-32 letters, digits, '-' or '_'");
    setBulkTag("");
    setTagging(false);
    bulk({ action: "add_tag", tag: t });
  }
  const resetTo = (set: (v: string) => void) => (e: { target: { value: string } }) => { set(e.target.value); setOffset(0); };
  const filtered = Boolean(status || q || issueType || rating || hasEmail || from || to || assignee || tag);
  /** The active filters other than the search box and the quick tabs, as removable chips for when the panel is closed. */
  const chips: { text: string; clear: () => void }[] = [
    status && { text: `Status: ${status}`, clear: () => setStatus("") },
    issueType && { text: `Type: ${label(issueType)}`, clear: () => setIssueType("") },
    rating && { text: `Rating: ${rating}★`, clear: () => setRating("") },
    hasEmail && { text: hasEmail === "true" ? "Has email" : "No email", clear: () => setHasEmail("") },
    assignee && assignee !== "none" && assignee !== me?.id && { text: `Assignee: ${assigneeLabel}`, clear: () => setAssignee("") },
    tag && { text: `Tag: ${tag}`, clear: () => setTag("") },
    from && { text: `From ${from}`, clear: () => setFrom("") },
    to && { text: `To ${to}`, clear: () => setTo("") },
  ].filter((c): c is { text: string; clear: () => void } => Boolean(c));
  const removeChip = (c: { clear: () => void }) => { c.clear(); setOffset(0); };
  const moreMenu: MenuItem[] = [{ label: exporting ? "Exporting…" : "Export CSV", onSelect: exportCsv }];
  const statusMenu: MenuItem[] = STATUSES.map((s) => ({ label: `Mark ${s}`, onSelect: () => bulk({ action: "set_status", status: s }) }));
  const tagMenu: MenuItem[] = [
    { label: "Add tag…", onSelect: () => setTagging(true) },
    ...(siteTags.length ? [{ label: "Remove tag" }, ...siteTags.map((t) => ({ label: t.tag, onSelect: () => bulk({ action: "remove_tag", tag: t.tag }) }))] : []),
  ];
  function clearFilters() {
    setStatus(""); setQ(""); setIssueType(""); setRating(""); setHasEmail(""); setFrom(""); setTo(""); setAssignee(""); setTag(""); setOffset(0);
  }

  async function remove(id: string) {
    if (!(await confirm({ title: "Delete this feedback?", message: "This cannot be undone.", confirmLabel: "Delete", danger: true }))) return;
    await toast.attempt(api(`/sites/${site.id}/feedback/${id}`, { method: "DELETE" }), "Feedback deleted");
    load();
  }

  const open = (id: string) => navigate(`/sites/${site.id}/feedback/${id}`);
  const quickTab = (value: string, text: string, count?: number) => (
    <button key={text} aria-pressed={assignee === value} onClick={() => { setAssignee(value); setOffset(0); }}>
      {text}{count !== undefined && <span className="count">{count}</span>}
    </button>
  );
  /** What the right-click / long-press menu and the ⋯ button offer for one item. */
  function menuFor(f: Feedback): MenuItem[] {
    const items: MenuItem[] = [{ label: "Open", onSelect: () => open(f.id) }];
    if (!canEdit) return items;
    items.push(
      ...STATUSES.filter((s) => s !== f.status).map((s) => ({ label: `Mark ${s}`, onSelect: () => setItemStatus(f.id, s) })),
      { label: "Assign to" },
      ...(me && canBeAssigned && f.assignee_id !== me.id
        ? [{ label: "Me", onSelect: () => patchItem(f.id, { assignee_id: me.id }) }] : []),
      ...(f.assignee_id ? [{ label: "Unassign", onSelect: () => patchItem(f.id, { assignee_id: null }) }] : []),
      ...recentAssignees(site.id)
        .filter((p) => p.user_id !== me?.id && p.user_id !== f.assignee_id)
        .slice(0, 4)
        .map((p) => ({ label: personName(p), onSelect: () => patchItem(f.id, { assignee_id: p.user_id }) })),
      { label: "More…", onSelect: (at) => picker.open(at, f.assignee_id, (p) => patchItem(f.id, { assignee_id: p?.user_id ?? null })) },
    );
    if (canDelete) items.push({ label: "Delete", danger: true, onSelect: () => remove(f.id) });
    return items;
  }
  /** The assignee on a card. Editors tap or click it (or press Enter) to change it right there. */
  function assigneeChip(f: Feedback) {
    const name = f.assignee_name;
    if (!canEdit) return name && <span className="assignee" title="Assignee">👤 {name}</span>;
    const change = (el: HTMLElement) => picker.open(below(el), f.assignee_id, (p) => patchItem(f.id, { assignee_id: p?.user_id ?? null }));
    return (
      <span
        className={`assignee editable${name ? "" : " none"}`}
        role="button"
        tabIndex={0}
        title="Change the assignee"
        onClick={(e) => change(e.currentTarget)}
        onKeyDown={(e) => e.key === "Enter" && change(e.currentTarget)}
      >
        👤 {name ?? "Unassigned"}
      </span>
    );
  }

  return (
    <>
      <div className="quick-tabs" role="group" aria-label="Whose feedback">
        {quickTab("", "All")}
        {me && canBeAssigned && quickTab(me.id, "Assigned to me", counts.mine)}
        {quickTab("none", "Unassigned", counts.unassigned)}
      </div>
      <div className="toolbar">
        <input
          className="search"
          placeholder="Search message, name, email"
          aria-label="Search feedback"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
        />
        <button className="filters-toggle" aria-expanded={filtersOpen} aria-controls="filters-panel" onClick={() => setFiltersOpen(!filtersOpen)}>
          Filters{chips.length > 0 && ` (${chips.length})`}
        </button>
        <button className="menu-btn" aria-label="More actions" aria-haspopup="menu" disabled={total === 0}
          onClick={(e) => ctx.openAt(e.currentTarget, moreMenu)}>⋯</button>
      </div>
      {chips.length > 0 && !filtersOpen && (
        <div className="active-chips">
          {chips.map((c) => <span key={c.text} className="chip">{c.text}<button aria-label={`Remove filter ${c.text}`} onClick={() => removeChip(c)}>×</button></span>)}
        </div>
      )}
      <div id="filters-panel" className="toolbar filters" data-open={filtersOpen || undefined}>
        <select value={status} onChange={resetTo(setStatus)} aria-label="Status">
          <option value="">All (excl. spam)</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        {issueTypes.length > 0 && (
          <select value={issueType} onChange={resetTo(setIssueType)} aria-label="Type of feedback">
            <option value="">All types</option>
            {issueTypes.map((t) => <option key={t.id} value={t.id}>{label(t.id)} ({t.count})</option>)}
          </select>
        )}
        <select value={rating} onChange={resetTo(setRating)} aria-label="Rating">
          <option value="">Any rating</option>
          {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{"★".repeat(n)}</option>)}
        </select>
        <select value={hasEmail} onChange={resetTo(setHasEmail)} aria-label="Email address">
          <option value="">Email or not</option>
          <option value="true">Has email</option>
          <option value="false">No email</option>
        </select>
        {assignee && assignee !== "none" && assignee !== me?.id ? (
          <span className="chip">Assignee: {assigneeLabel}<button aria-label="Remove the assignee filter" onClick={() => { setAssignee(""); setOffset(0); }}>×</button></span>
        ) : (
          <button onClick={(e) => picker.open(below(e.currentTarget), undefined, (p) => { setAssignee(p!.user_id); setAssigneeLabel(personName(p!)); setOffset(0); }, false)}>Assignee…</button>
        )}
        {siteTags.length > 0 && (
          <select value={tag} onChange={resetTo(setTag)} aria-label="Tag">
            <option value="">Any tag</option>
            {siteTags.map((t) => <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>)}
          </select>
        )}
        <label className="muted">From <input type="date" value={from} max={to || undefined} onChange={resetTo(setFrom)} /></label>
        <label className="muted">To <input type="date" value={to} min={from || undefined} onChange={resetTo(setTo)} /></label>
        {filtered && <button onClick={clearFilters}>Clear filters</button>}
      </div>
      {canEdit && items.length > 0 && (
        <div className="toolbar bulk">
          <label>
            <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((f) => f.id)))} />
            {" "}{selected.size > 0 ? `${selected.size} selected` : "Select all on this page"}
          </label>
        </div>
      )}
      <datalist id="site-tags">{siteTags.map((t) => <option key={t.tag} value={t.tag} />)}</datalist>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && !error && <p className="empty-state">No feedback found.</p>}
      {items.map((f) => (
        <article key={f.id} className={`card fb compact ${f.status}`} {...ctx.bind(() => menuFor(f))}>
          <header>
            {canEdit && <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} aria-label="Select this feedback" />}
            <FeedbackBadges f={f} />
            <time className="muted grow-end" dateTime={f.created_at} title={new Date(f.created_at).toLocaleString()}>{ago(f.created_at)}</time>
            <button className="menu-btn" aria-label="Actions" aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, menuFor(f))}>⋯</button>
          </header>
          {/* Rendered as text by React; never as HTML. */}
          <p className="message"><a href={`/sites/${site.id}/feedback/${f.id}`} onClick={(e) => { e.preventDefault(); open(f.id); }}>{f.message}</a></p>
          {(f.name || f.email) && <p className="muted">{[f.name, f.email].filter(Boolean).join(" · ")}</p>}
          <div className="tags">
            {assigneeChip(f)}
            {f.tags.map((t) => <span key={t} className="tag static">{t}</span>)}
            {f.reply_count > 0 && <span className="muted" title={`Replied ${f.reply_count} time${f.reply_count === 1 ? "" : "s"}`}>↩ Replied</span>}
            {f.note_count > 0 && (
              <a className="note-count" href={`/sites/${site.id}/feedback/${f.id}`} onClick={(e) => { e.preventDefault(); open(f.id); }}
                title={`${f.note_count} internal note${f.note_count === 1 ? "" : "s"}`}>💬 {f.note_count}</a>
            )}
          </div>
        </article>
      ))}
      {canEdit && selected.size > 0 && (
        <div className="bulk-bar" role="toolbar" aria-label="Actions for the selected feedback">
          <strong>{selected.size} selected</strong>
          <button aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, statusMenu)}>Status ▾</button>
          <button onClick={(e) => picker.open(below(e.currentTarget), undefined, (p) => bulk({ action: "assign", assignee_id: p?.user_id ?? null }))}>Assign…</button>
          <button aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, tagMenu)}>Tags ▾</button>
          {canDelete && <button className="danger" onClick={() => bulk({ action: "delete" })}>Delete</button>}
          {tagging && (
            <form className="inline" onSubmit={(e) => { e.preventDefault(); bulkAddTag(); }}>
              <input value={bulkTag} onChange={(e) => setBulkTag(e.target.value)} placeholder="Tag selected…" maxLength={32} aria-label="Tag to add to selected" list="site-tags" autoFocus />
            </form>
          )}
        </div>
      )}
      {ctx.node}
      {picker.node}
      <div className="toolbar">
        <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Previous</button>
        <span className="muted">{total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
        <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
      </div>
    </>
  );
}

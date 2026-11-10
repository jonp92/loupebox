import { autoFocusField } from "../focus";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, download, json, type Feedback, type Role, type Site, type Status } from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";
import { Bar, Placeholder } from "../Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { Icon } from "../icons";
import { useLive } from "../live";
import { fmtCount } from "../unread";
import { FieldFilterSheet, fieldChips, type FieldValues } from "../fieldFilters";
import {
  FeedbackBadges, TAG_PATTERN, ago, below, label, personName, recentAssignees, slug, useAssigneePicker, useContextMenu, type MenuItem,
} from "../triage";

type Density = "comfortable" | "compact";
type QuickCounts = {
  mine: number; mine_capped?: boolean; unassigned: number; unassigned_capped?: boolean; unread?: number; unread_capped?: boolean;
};
/** A feedback item as listed; the inbox also says which site it is on and the caller's role there. */
type Item = Feedback & { site_id?: string; site_name?: string; my_role?: Role };
const canEditRole = (role: Role | null | undefined) => role === "editor" || role === "admin";
const PAGE_SIZE: Record<Density, number> = { comfortable: 25, compact: 50 };
const DENSITY_KEY = "loupebox.feedback-density";
/** The list density chosen in this browser. Compact rows only apply on wide screens (see styles.css). */
function savedDensity(): Density {
  try {
    return localStorage.getItem(DENSITY_KEY) === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable";
  }
}
const STATUSES: Status[] = ["new", "read", "archived", "spam"];

/** One site's feedback (`site` given), or the feedback of every site the caller can see (the inbox). */
const SORTS = [["newest", "Newest first"], ["unread", "Unread first"], ["status", "By status"], ["oldest", "Oldest first"], ["rating_high", "Highest rating"], ["rating_low", "Lowest rating"]];

export default function FeedbackList({ site }: { site?: Site }) {
  const confirm = useConfirm();
  const toast = useToast();
  const { me } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [totalCapped, setTotalCapped] = useState(false); // more than `total` match
  const [loading, setLoading] = useState(true); // a list request is in flight
  const latest = useRef(0); // only the newest request ends the loading state
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useSearchParams(); // ?status= pre-selects the filter, e.g. from the dashboard
  const [status, setStatus] = useState(() => STATUSES.find((s) => s === search.get("status")) ?? "");
  // The inbox only: the sites to choose from, the one chosen (?site=), and who it is for (?assignee=me|none).
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState(() => search.get("site") ?? "");
  const focus = site ?? sites.find((s) => s.id === siteId); // the one site per-site menus (tags, types, people) are about
  const base = site ? `/sites/${site.id}/feedback` : "/inbox";
  const sidOf = (f: Item) => f.site_id ?? site!.id;
  const mayEdit = (f: Item) => canEditRole(f.my_role ?? site?.my_role);
  const mayDelete = (f: Item) => (f.my_role ?? site?.my_role) === "admin";
  /** The assignee picker is for one site, so it only serves items of the site the list is focused on. */
  const pickable = (f: Item) => focus?.id === sidOf(f);
  const canBeAssignedOn = (siteIdOf: string) => Boolean(me?.memberships.some((m) => m.site_id === siteIdOf && m.role !== "viewer"));
  const [q, setQ] = useState("");
  const [issueType, setIssueType] = useState("");
  const [issueTypes, setIssueTypes] = useState<{ id: string; count: number }[]>([]);
  const [rating, setRating] = useState("");
  const [hasEmail, setHasEmail] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [assignee, setAssignee] = useState(() => {
    const a = search.get("assignee");
    return a === "none" ? a : a === "me" ? me?.id ?? "" : "";
  });
  const [tag, setTag] = useState("");
  const [sort, setSort] = useState("newest"); // the order only; unlike a filter it never narrows the list
  const [fieldFilters, setFieldFilters] = useState<FieldValues>({});
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const picker = useAssigneePicker(focus?.id ?? "");
  const [assigneeLabel, setAssigneeLabel] = useState(""); // who a per-person filter is for
  const [counts, setCounts] = useState<QuickCounts | null>(null); // null until loaded
  const ctx = useContextMenu();
  const [siteTags, setSiteTags] = useState<{ tag: string; count: number }[]>([]);
  const [bulkTag, setBulkTag] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false); // small screens only; wide ones always show the filters
  const [tagging, setTagging] = useState(false);
  const [density, setDensityState] = useState(savedDensity);
  const pageSize = PAGE_SIZE[density];
  const canDelete = site?.my_role === "admin"; // bulk delete is a per-site action
  const canEdit = site ? canEditRole(site.my_role) : items.some(mayEdit); // something on the page can be changed
  // Only editors and admins hold assignments, and a superadmin who is not a member cannot.
  const canBeAssigned = site
    ? canBeAssignedOn(site.id)
    : Boolean(me?.memberships.some((m) => m.role !== "viewer"));

  /** The list's filters as query params; the CSV export takes the same ones. */
  const filterParams = useCallback(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (!site && siteId) params.set("site_id", siteId);
    if (q) params.set("q", q);
    if (issueType) params.set("issue_type", issueType);
    if (rating) params.set("rating", rating);
    if (hasEmail) params.set("has_email", hasEmail);
    if (from) params.set("created_from", from);
    if (to) params.set("created_to", to);
    if (assignee) params.set("assignee", assignee);
    if (tag) params.set("tag", tag);
    for (const [id, value] of Object.entries(fieldFilters)) params.append("cf", `${id}:${value}`);
    return params;
  }, [site, siteId, status, q, issueType, rating, hasEmail, from, to, assignee, tag, fieldFilters]);

  /** `quiet`: a live refresh, which keeps the selection and does not dim the list. */
  const load = useCallback((quiet?: boolean) => {
    const params = filterParams();
    params.set("limit", String(pageSize));
    params.set("offset", String(offset));
    params.set("sort", sort);
    const mine = ++latest.current;
    if (!quiet) setLoading(true);
    api<{ items: Item[]; total: number; total_capped?: boolean }>(`${base}?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setTotalCapped(Boolean(r.total_capped));
        if (!quiet) setSelected(new Set()); // a new page or filter never keeps a hidden selection
        setError("");
      })
      .catch((e) => setError(e.message))
      .finally(() => mine === latest.current && setLoading(false));
    api<QuickCounts>(site ? `${base}/counts` : `${base}/counts${siteId ? `?site_id=${siteId}` : ""}`).then(setCounts, () => undefined);
  }, [base, site, siteId, offset, pageSize, sort, filterParams]);
  useEffect(() => load(), [load]);
  useLive(() => load(true), (e) => !site || e.site_id === site.id);
  // The inbox's site menu, and its filters in the address so the item page's back link can restore them.
  useEffect(() => {
    if (!site) api<Site[]>("/sites").then(setSites, () => setSites([]));
  }, [site]);
  useEffect(() => {
    if (site) return;
    const next = new URLSearchParams();
    if (siteId) next.set("site", siteId);
    if (status) next.set("status", status);
    if (assignee === "none" || (assignee && assignee === me?.id)) next.set("assignee", assignee === "none" ? "none" : "me");
    setSearch(next, { replace: true });
  }, [site, siteId, status, assignee, me?.id, setSearch]);
  // The kinds of feedback visitors have tagged (from the widget's badges), for the filter.
  useEffect(() => {
    if (!focus) return setIssueTypes([]);
    api<{ id: string; count: number }[]>(`/sites/${focus.id}/feedback/issue-types`).then(setIssueTypes, () => setIssueTypes([]));
  }, [focus?.id]);
  const loadTags = useCallback(() => {
    if (!focus) return setSiteTags([]);
    api<{ tag: string; count: number }[]>(`/sites/${focus.id}/feedback/tags`).then(setSiteTags, () => setSiteTags([]));
  }, [focus?.id]);
  useEffect(loadTags, [loadTags]);
  /** Change one item (status, assignee or tags) and reload. */
  async function patchItem(f: Item, body: Partial<{ status: Status; assignee_id: string | null; tags: string[] }>) {
    await toast.attempt(api(`/sites/${sidOf(f)}/feedback/${f.id}`, json("PATCH", body)));
    load();
    if (body.tags) loadTags();
  }
  const setItemStatus = (f: Item, next: Status) => patchItem(f, { status: next });
  async function exportCsv() {
    const params = filterParams();
    setExporting(true);
    await toast.attempt(download(`/sites/${site!.id}/feedback/export.csv?${params}`, "feedback.csv"), "Export downloaded");
    setExporting(false);
  }
  function toggle(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }
  const editable = items.filter(mayEdit);
  const allSelected = editable.length > 0 && editable.every((f) => selected.has(f.id));
  type BulkBody =
    | { action: "set_status"; status: Status }
    | { action: "assign"; assignee_id: string | null }
    | { action: "assign_me" | "unassign" } // the inbox's only assignments
    | { action: "add_tag" | "remove_tag"; tag: string }
    | { action: "delete" };
  async function bulk(body: BulkBody) {
    if (body.action === "delete" && !(await confirm({
      title: `Delete ${selected.size} feedback item${selected.size === 1 ? "" : "s"}?`,
      message: "This cannot be undone.", confirmLabel: "Delete", danger: true,
    }))) return;
    await toast.attempt(
      api<{ affected: number; skipped: number }>(`${base}/bulk`, json("POST", { ids: [...selected], ...body }))
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
  /** Choosing another site drops the filters that only make sense for the last one. */
  function pickSite(id: string) {
    setSiteId(id);
    setIssueType("");
    setTag("");
    if (assignee !== "none" && assignee !== me?.id) setAssignee("");
    setOffset(0);
  }
  const filtered = Boolean(siteId || status || q || issueType || rating || hasEmail || from || to || assignee || tag || Object.keys(fieldFilters).length > 0);
  /** The active filters other than the search box and the quick tabs, as removable chips for when the panel is closed. */
  const chips: { text: string; clear: () => void }[] = [
    !site && focus && { text: `Site: ${focus.name}`, clear: () => pickSite("") },
    status && { text: `Status: ${status}`, clear: () => setStatus("") },
    issueType && { text: `Type: ${label(issueType)}`, clear: () => setIssueType("") },
    rating && { text: `Rating: ${rating}★`, clear: () => setRating("") },
    hasEmail && { text: hasEmail === "true" ? "Has email" : "No email", clear: () => setHasEmail("") },
    assignee && assignee !== "none" && assignee !== me?.id && { text: `Assignee: ${assigneeLabel}`, clear: () => setAssignee("") },
    tag && { text: `Tag: ${tag}`, clear: () => setTag("") },
    ...fieldChips(site?.custom_fields ?? [], fieldFilters).map((c) => ({
      text: c.text, clear: () => setFieldFilters(Object.fromEntries(Object.entries(fieldFilters).filter(([id]) => id !== c.id))),
    })),
    from && { text: `From ${from}`, clear: () => setFrom("") },
    to && { text: `To ${to}`, clear: () => setTo("") },
  ].filter((c): c is { text: string; clear: () => void } => Boolean(c));
  function setDensity(d: Density) {
    setDensityState(d);
    setOffset(0);
    try {
      localStorage.setItem(DENSITY_KEY, d);
    } catch {
      // storage unavailable: the choice lasts until the page is reloaded
    }
  }

  const removeChip = (c: { clear: () => void }) => { c.clear(); setOffset(0); };
  const moreMenu: MenuItem[] = site ? [{ label: exporting ? "Exporting…" : "Export CSV", onSelect: exportCsv }] : [];
  const statusMenu: MenuItem[] = STATUSES.map((s) => ({ label: `Mark ${s}`, onSelect: () => bulk({ action: "set_status", status: s }) }));
  const tagMenu: MenuItem[] = [
    { label: "Add tag…", onSelect: () => setTagging(true) },
    ...(siteTags.length ? [{ label: "Remove tag" }, ...siteTags.map((t) => ({ label: t.tag, onSelect: () => bulk({ action: "remove_tag", tag: t.tag }) }))] : []),
  ];
  function clearFilters() {
    setSiteId(""); setStatus(""); setQ(""); setIssueType(""); setRating(""); setHasEmail(""); setFrom(""); setTo(""); setAssignee(""); setTag(""); setFieldFilters({}); setOffset(0);
  }

  async function remove(f: Item) {
    if (!(await confirm({ title: "Delete this feedback?", message: "This cannot be undone.", confirmLabel: "Delete", danger: true }))) return;
    await toast.attempt(api(`/sites/${sidOf(f)}/feedback/${f.id}`, { method: "DELETE" }), "Feedback deleted");
    load();
  }

  const href = (f: Item) => `/sites/${sidOf(f)}/feedback/${f.id}`;
  /** The item page's back link returns here, with the inbox's site, status and person still chosen. */
  const open = (f: Item) => navigate(href(f), { state: { from: location.pathname + location.search } });
  /** A plain click opens the item in the app; Cmd/Ctrl/Shift-click and middle-click are left to the browser (new tab). */
  const openOnPlainClick = (f: Item) => (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    open(f);
  };
  /** A quick tab sets the person filter, and the status too when it names one (the inbox's "All" and "Unread"). */
  const quickTab = (text: string, view: { assignee?: string; status?: Status | "" }, count?: string | null) => {
    const pressed = assignee === (view.assignee ?? "") && (view.status === undefined || view.status === status);
    return (
      <button key={text} aria-pressed={pressed} onClick={() => {
        setAssignee(view.assignee ?? "");
        if (view.status !== undefined) setStatus(view.status);
        setOffset(0);
      }}>
        {text}{count != null && <span className="count">{count}</span>}
      </button>
    );
  };
  /** What the right-click / long-press menu and the ⋯ button offer for one item. */
  function menuFor(f: Item): MenuItem[] {
    const items: MenuItem[] = [{ label: "Open", onSelect: () => open(f) }];
    if (!mayEdit(f)) return items;
    items.push(
      ...STATUSES.filter((s) => s !== f.status).map((s) => ({ label: `Mark ${s}`, onSelect: () => setItemStatus(f, s) })),
      { label: "Assign to" },
      ...(me && canBeAssignedOn(sidOf(f)) && f.assignee_id !== me.id
        ? [{ label: "Me", onSelect: () => patchItem(f, { assignee_id: me.id }) }] : []),
      ...(f.assignee_id ? [{ label: "Unassign", onSelect: () => patchItem(f, { assignee_id: null }) }] : []),
    );
    if (pickable(f)) {
      items.push(
        ...recentAssignees(sidOf(f))
          .filter((p) => p.user_id !== me?.id && p.user_id !== f.assignee_id)
          .slice(0, 4)
          .map((p) => ({ label: personName(p), onSelect: () => patchItem(f, { assignee_id: p.user_id }) })),
        { label: "More…", onSelect: (at) => picker.open(at, f.assignee_id, (p) => patchItem(f, { assignee_id: p?.user_id ?? null })) },
      );
    }
    if (mayDelete(f)) items.push({ label: "Delete", danger: true, onSelect: () => remove(f) });
    return items;
  }
  /** The assignee on a card. Editors tap or click it (or press Enter) to change it right there. */
  function assigneeChip(f: Item) {
    const name = f.assignee_name;
    if (!mayEdit(f) || !pickable(f)) return name && <span className="assignee" title="Assignee"><Icon name="person" size={16} />{name}</span>;
    const change = (el: HTMLElement) => picker.open(below(el), f.assignee_id, (p) => patchItem(f, { assignee_id: p?.user_id ?? null }));
    return (
      <span
        className={`assignee editable${name ? "" : " none"}`}
        role="button"
        tabIndex={0}
        title="Change the assignee"
        onClick={(e) => change(e.currentTarget)}
        onKeyDown={(e) => e.key === "Enter" && change(e.currentTarget)}
      >
        <Icon name="person" size={16} />{name ?? "Unassigned"}
      </span>
    );
  }

  return (
    <>
      <div className="list-head">
        <div className="quick-tabs" role="group" aria-label="Whose feedback">
          {quickTab("All", site ? {} : { status: "" })}
          {!site && quickTab("Unread", { status: "new" }, counts?.unread != null ? fmtCount(counts.unread, Boolean(counts.unread_capped)) : null)}
          {me && canBeAssigned && quickTab("My work", { assignee: me.id }, counts && fmtCount(counts.mine, Boolean(counts.mine_capped)))}
          {quickTab("Unassigned", { assignee: "none" }, counts && fmtCount(counts.unassigned, Boolean(counts.unassigned_capped)))}
        </div>
        <div className="density" role="radiogroup" aria-label="List density">
          {(["comfortable", "compact"] as const).map((d) => (
            <label key={d}>
              <input type="radio" name="density" value={d} checked={density === d} onChange={() => setDensity(d)} />
              {d === "compact" ? "Compact" : "Comfortable"}
            </label>
          ))}
        </div>
      </div>
      <div className="toolbar">
        <input
          className="search"
          placeholder="Search message, name, email"
          aria-label="Search feedback"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
        />
        <select value={sort} onChange={resetTo(setSort)} aria-label="Sort by">
          {SORTS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select>
        <button className="filters-toggle" aria-expanded={filtersOpen} aria-controls="filters-panel" onClick={() => setFiltersOpen(!filtersOpen)}>
          Filters{chips.length > 0 && ` (${chips.length})`}
        </button>
        {moreMenu.length > 0 && (
          <button className="menu-btn" aria-label="More actions" aria-haspopup="menu" disabled={total === 0}
            onClick={(e) => ctx.openAt(e.currentTarget, moreMenu)}><Icon name="more" /></button>
        )}
      </div>
      {chips.length > 0 && !filtersOpen && (
        <div className="active-chips">
          {chips.map((c) => <span key={c.text} className="chip">{c.text}<button aria-label={`Remove filter ${c.text}`} onClick={() => removeChip(c)}>×</button></span>)}
        </div>
      )}
      <div id="filters-panel" className="toolbar filters" data-open={filtersOpen || undefined}>
        {!site && sites.length > 1 && (
          <select value={siteId} onChange={(e) => pickSite(e.target.value)} aria-label="Site">
            <option value="">All sites</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
        <select value={status} onChange={resetTo(setStatus)} aria-label="Status">
          <option value="">Any status (not spam)</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        {issueTypes.length > 0 && (
          <select value={issueType} onChange={resetTo(setIssueType)} aria-label="Type of feedback">
            <option value="">Any type</option>
            {issueTypes.map((t) => <option key={t.id} value={t.id}>{label(t.id)} ({t.count})</option>)}
          </select>
        )}
        <select value={rating} onChange={resetTo(setRating)} aria-label="Rating">
          <option value="">Any rating</option>
          {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{"★".repeat(n)}</option>)}
        </select>
        <select value={hasEmail} onChange={resetTo(setHasEmail)} aria-label="Email address">
          <option value="">Any email</option>
          <option value="true">Has email</option>
          <option value="false">No email</option>
        </select>
        {assignee && assignee !== "none" && assignee !== me?.id ? (
          <span className="chip">Assignee: {assigneeLabel}<button aria-label="Remove the assignee filter" onClick={() => { setAssignee(""); setOffset(0); }}>×</button></span>
        ) : focus && (
          <button onClick={(e) => picker.open(below(e.currentTarget), undefined, (p) => { setAssignee(p!.user_id); setAssigneeLabel(personName(p!)); setOffset(0); }, false)}>Any assignee</button>
        )}
        {siteTags.length > 0 && (
          <select value={tag} onChange={resetTo(setTag)} aria-label="Tag">
            <option value="">Any tag</option>
            {siteTags.map((t) => <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>)}
          </select>
        )}
        {site && site.custom_fields.length > 0 && (
          <button onClick={() => setFieldsOpen(true)}>Custom fields</button>
        )}
        <div className="date-range">
          <label className="muted">From <input type="date" value={from} max={to || undefined} onChange={resetTo(setFrom)} /></label>
          <label className="muted">To <input type="date" value={to} min={from || undefined} onChange={resetTo(setTo)} /></label>
        </div>
        {filtered && <button onClick={clearFilters}>Clear filters</button>}
      </div>
      {canEdit && items.length > 0 && (
        <div className="toolbar bulk">
          <label>
            <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(editable.map((f) => f.id)))} />
            {" "}{selected.size > 0 ? `${selected.size} selected` : "Select all on this page"}
          </label>
        </div>
      )}
      {site && (
        <FieldFilterSheet open={fieldsOpen} fields={site.custom_fields} values={fieldFilters}
          onApply={(v) => { setFieldFilters(v); setOffset(0); }} onClose={() => setFieldsOpen(false)} />
      )}
      <datalist id="site-tags">{siteTags.map((t) => <option key={t.tag} value={t.tag} />)}</datalist>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && !error && (loading ? (
        <Placeholder label="Loading feedback">
          {[70, 85, 60, 78, 65].map((w, i) => (
            <div key={i} className="fb-ph ph"><Bar w="7rem" h=".8rem" /><Bar w={`${w}%`} /></div>
          ))}
        </Placeholder>
      ) : (
        <EmptyState>No feedback found.</EmptyState>
      ))}
      <div className={loading ? "is-refreshing" : undefined} aria-busy={loading && items.length > 0}>
      {items.map((f) => (
        <article key={f.id} className={`card fb compact ${f.status}${density === "compact" ? " dense" : ""}${site ? "" : " with-site"}`} {...ctx.bind(() => menuFor(f))}>
          <header>
            {mayEdit(f) && <label className="check"><input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} aria-label="Select this feedback" /></label>}
            <span className="fb-badges"><FeedbackBadges f={f} fields={site?.custom_fields} /></span>
            {!site && <span className="fb-site" title={f.site_name}>{f.site_name}</span>}
            <time className="muted grow-end" dateTime={f.created_at} title={new Date(f.created_at).toLocaleString()}>{ago(f.created_at)}</time>
            <button className="menu-btn" aria-label="Actions" aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, menuFor(f))}><Icon name="more" /></button>
          </header>
          {/* Rendered as text by React; never as HTML. */}
          <p className="message"><a href={href(f)} onClick={openOnPlainClick(f)}>{f.message}</a></p>
          {(f.name || f.email) && <p className="person">{[f.name, f.email].filter(Boolean).join(" · ")}</p>}
          <div className="tags">
            {assigneeChip(f)}
            {f.tags.map((t) => <span key={t} className="tag static">{t}</span>)}
            {f.reply_count > 0 && <span className="replied" title={`Replied ${f.reply_count} time${f.reply_count === 1 ? "" : "s"}`}><Icon name="reply" size={16} />Replied</span>}
            {f.attachment_count > 0 && (
              <a className="note-count" href={href(f)} onClick={openOnPlainClick(f)}
                title={`${f.attachment_count} image${f.attachment_count === 1 ? "" : "s"}`}>
                <Icon name="clip" size={16} />{f.attachment_count}<span className="sr-only"> image{f.attachment_count === 1 ? "" : "s"}</span>
              </a>
            )}
            {f.note_count > 0 && (
              <a className="note-count" href={href(f)} onClick={openOnPlainClick(f)}
                title={`${f.note_count} internal note${f.note_count === 1 ? "" : "s"}`}><Icon name="note" size={16} />{f.note_count}<span className="sr-only"> internal note{f.note_count === 1 ? "" : "s"}</span></a>
            )}
          </div>
        </article>
      ))}
      </div>
      {canEdit && selected.size > 0 && (
        <div className="bulk-bar" role="toolbar" aria-label="Actions for the selected feedback">
          <strong>{selected.size} selected</strong>
          <button aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, statusMenu)}>Status ▾</button>
          {site ? (
            <>
              <button onClick={(e) => picker.open(below(e.currentTarget), undefined, (p) => bulk({ action: "assign", assignee_id: p?.user_id ?? null }))}>Assign…</button>
              <button aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, tagMenu)}>Tags ▾</button>
              {canDelete && <button className="danger" onClick={() => bulk({ action: "delete" })}>Delete</button>}
            </>
          ) : (
            <>
              <button onClick={() => bulk({ action: "assign_me" })}>Assign to me</button>
              <button onClick={() => bulk({ action: "unassign" })}>Unassign</button>
            </>
          )}
          {tagging && (
            <form className="inline" onSubmit={(e) => { e.preventDefault(); bulkAddTag(); }}>
              <input value={bulkTag} onChange={(e) => setBulkTag(e.target.value)} placeholder="Tag selected…" maxLength={32} aria-label="Tag to add to selected" list="site-tags" autoFocus={autoFocusField} />
            </form>
          )}
        </div>
      )}
      {ctx.node}
      {picker.node}
      {!(loading && items.length === 0) && <div className="toolbar">
        <button disabled={offset === 0} onClick={() => setOffset(offset - pageSize)}>Previous</button>
        <span className="muted num">{total === 0 ? 0 : offset + 1}–{Math.min(offset + pageSize, total)} of {fmtCount(total, totalCapped)}</span>
        <button disabled={!totalCapped && offset + pageSize >= total} onClick={() => setOffset(offset + pageSize)}>Next</button>
      </div>}
    </>
  );
}

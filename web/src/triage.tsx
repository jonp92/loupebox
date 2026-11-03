import {
  useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent, type ReactNode,
} from "react";
import { api, json, type Assignee, type Feedback, type Note } from "./api";
import { useToast } from "./toast";

/** The widget's badge ids are plain slugs; anything else in metadata is not shown as a badge. */
export const ISSUE_TYPE = /^[a-z0-9_-]{1,32}$/;
export const label = (id: string) => id.replace(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase());
export const safeHref = (url: string | null) => (url && /^https?:\/\//i.test(url) ? url : null);

/** "5m", "3h", "2d" for the last month, then the date. The full time belongs in a title. */
export function ago(iso: string) {
  const mins = Math.max(0, (Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${Math.floor(mins)}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h`;
  if (mins < 43200) return `${Math.floor(mins / 1440)}d`;
  return new Date(iso).toLocaleDateString();
}

export const TAG_PATTERN = /^[a-z0-9][a-z0-9_-]{0,31}$/;
/** Same normalisation as the server, so what is shown is what is saved. */
export const slug = (v: string) => v.trim().toLowerCase().replace(/\s+/g, "-");

/** Status, kind, rating and date: the top line of every feedback card. */
export function FeedbackBadges({ f }: { f: Feedback }) {
  return (
    <>
      <span className={`badge ${f.status}`}>{f.status}</span>
      {typeof f.metadata.issue_type === "string" && ISSUE_TYPE.test(f.metadata.issue_type) && (
        <span className="badge kind" data-kind={f.metadata.issue_type} title="Type chosen by the visitor">{label(f.metadata.issue_type)}</span>
      )}
      {f.rating && <span className="stars" title={`${f.rating} / 5`}>{"★".repeat(f.rating)}<span className="dim">{"★".repeat(5 - f.rating)}</span></span>}
    </>
  );
}

// ---- popovers: the context menu and the assignee picker

export interface Point { x: number; y: number }

/** A floating panel at a screen point, kept inside the window. Closes on Escape, an outside press, or when the page
 * scrolls or resizes (scrolling inside the panel is fine). */
function Popover({ at, onClose, className, children }: { at: Point; onClose: () => void; className: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: at.x, top: at.y });
  useLayoutEffect(() => {
    const r = ref.current!.getBoundingClientRect();
    setPos({ left: Math.max(4, Math.min(at.x, innerWidth - r.width - 4)), top: Math.max(4, Math.min(at.y, innerHeight - r.height - 4)) });
  }, [at.x, at.y]);
  useEffect(() => {
    const inside = (e: Event) => ref.current?.contains(e.target as Node);
    const outside = (e: Event) => { if (!inside(e)) onClose(); };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const scroll = (e: Event) => { if (!inside(e)) onClose(); };
    addEventListener("pointerdown", outside, true);
    addEventListener("keydown", key);
    addEventListener("scroll", scroll, true);
    addEventListener("resize", onClose);
    return () => {
      removeEventListener("pointerdown", outside, true);
      removeEventListener("keydown", key);
      removeEventListener("scroll", scroll, true);
      removeEventListener("resize", onClose);
    };
  }, [onClose]);
  return <div ref={ref} className={className} style={pos}>{children}</div>;
}

export interface MenuItem {
  label: string;
  onSelect?: (at: Point) => void; // omitted: a heading
  danger?: boolean;
  current?: boolean;
}

export function ContextMenu({ at, items, onClose }: { at: Point; items: MenuItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const buttons = () => [...ref.current!.querySelectorAll<HTMLButtonElement>("button")];
  // Scrolling to the first item would close the menu, so focus without it.
  useEffect(() => buttons()[0]?.focus({ preventScroll: true }), []);
  function arrows(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const btns = buttons();
    const i = btns.indexOf(document.activeElement as HTMLButtonElement);
    btns[(i + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length]?.focus({ preventScroll: true });
  }
  return (
    <Popover at={at} onClose={onClose} className="ctx-menu">
      <div ref={ref} role="menu" onKeyDown={arrows}>
        {items.map((it, n) =>
          it.onSelect ? (
            <button key={n} role="menuitem" className={it.danger ? "danger" : undefined} onClick={() => { onClose(); it.onSelect!(at); }}>
              {it.current ? "✓ " : ""}{it.label}
            </button>
          ) : (
            <div key={n} className="ctx-heading muted">{it.label}</div>
          ),
        )}
      </div>
    </Popover>
  );
}

const LONG_PRESS_MS = 500;

/** Handlers that open a menu on right-click or a long touch press, plus `openAt` for a visible "⋯" button. */
export function useContextMenu() {
  const [menu, setMenu] = useState<{ at: Point; items: MenuItem[] } | null>(null);
  const timer = useRef<number>();
  const fired = useRef(false);
  const cancel = () => window.clearTimeout(timer.current);
  const bind = (items: () => MenuItem[]) => ({
    onContextMenu: (e: React.MouseEvent) => {
      e.preventDefault();
      setMenu({ at: { x: e.clientX, y: e.clientY }, items: items() });
    },
    onPointerDown: (e: ReactPointerEvent) => {
      fired.current = false;
      if (e.pointerType !== "touch") return;
      const at = { x: e.clientX, y: e.clientY };
      timer.current = window.setTimeout(() => { fired.current = true; setMenu({ at, items: items() }); }, LONG_PRESS_MS);
    },
    onPointerMove: cancel,
    onPointerUp: cancel,
    onPointerCancel: cancel,
    // The tap that ends a long press must not also follow a link underneath it.
    onClickCapture: (e: React.MouseEvent) => { if (fired.current) { e.preventDefault(); e.stopPropagation(); fired.current = false; } },
  });
  const openAt = (el: HTMLElement, items: MenuItem[]) => {
    const r = el.getBoundingClientRect();
    setMenu({ at: { x: r.left, y: r.bottom }, items });
  };
  const close = useCallback(() => setMenu(null), []);
  return { bind, openAt, node: menu && <ContextMenu at={menu.at} items={menu.items} onClose={close} /> };
}

// ---- assignees: found by searching, never listed in full (a site can have many members)

const RECENT_MAX = 5;
const recentKey = (siteId: string) => `loupebox.recent-assignees.${siteId}`;

/** The people you assigned to most recently on this site. Kept in this browser only; it is a convenience. */
export function recentAssignees(siteId: string): Assignee[] {
  try {
    const list = JSON.parse(localStorage.getItem(recentKey(siteId)) ?? "[]");
    return Array.isArray(list) ? list.filter((p) => p && typeof p.user_id === "string").slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}
function rememberAssignee(siteId: string, person: Assignee) {
  try {
    const rest = recentAssignees(siteId).filter((p) => p.user_id !== person.user_id);
    localStorage.setItem(recentKey(siteId), JSON.stringify([person, ...rest].slice(0, RECENT_MAX)));
  } catch {
    // storage unavailable: no recents, nothing else changes
  }
}

export const personName = (p: Pick<Assignee, "name" | "email">) => p.name || p.email;

function AssigneePicker({ siteId, at, current, allowNone, onPick, onClose }: {
  siteId: string; at: Point; current?: string | null; allowNone: boolean; onPick: (p: Assignee | null) => void; onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Assignee[]>([]);
  const [active, setActive] = useState(0);
  useEffect(() => {
    const t = window.setTimeout(() => {
      api<Assignee[]>(`/sites/${siteId}/feedback/assignees?q=${encodeURIComponent(q)}`).then(setFound, () => setFound([]));
    }, q ? 200 : 0);
    return () => window.clearTimeout(t);
  }, [siteId, q]);
  // With nothing typed, your recent people come first; then whoever the search returned.
  const people = (q ? [] : recentAssignees(siteId)).concat(found).filter((p, i, all) => all.findIndex((x) => x.user_id === p.user_id) === i);
  const rows: (Assignee | null)[] = [...(allowNone && !q ? [null] : []), ...people];
  const pick = (p: Assignee | null) => { onClose(); if (p) rememberAssignee(siteId, p); onPick(p); };
  function key(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i + (e.key === "ArrowDown" ? 1 : rows.length - 1)) % Math.max(rows.length, 1));
    } else if (e.key === "Enter" && rows.length) {
      e.preventDefault();
      pick(rows[Math.min(active, rows.length - 1)]);
    }
  }
  return (
    <Popover at={at} onClose={onClose} className="picker-pop">
      <input autoFocus value={q} placeholder="Find a person…" aria-label="Find a person" onChange={(e) => { setQ(e.target.value); setActive(0); }} onKeyDown={key} />
      <ul role="listbox">
        {rows.map((p, i) => (
          <li key={p?.user_id ?? "none"} role="option" aria-selected={i === active} className={i === active ? "active" : undefined}
            onMouseEnter={() => setActive(i)} onClick={() => pick(p)}>
            {p ? personName(p) : "Unassigned"}
            {p && <span className="muted"> {p.email}</span>}
            {current !== undefined && (p ? p.user_id === current : current === null) && " ✓"}
          </li>
        ))}
        {rows.length === 0 && <li className="muted">{q ? "No one matches." : "Loading…"}</li>}
      </ul>
    </Popover>
  );
}

/** Opens the assignee picker at a point. `open` takes who is current (`undefined`: no one, as when assigning
 * several items) and what to do with the choice
 * (`null` means unassign, offered only when `allowNone`). */
export function useAssigneePicker(siteId: string) {
  const [state, setState] = useState<{ at: Point; current?: string | null; allowNone: boolean; onPick: (p: Assignee | null) => void } | null>(null);
  const close = useCallback(() => setState(null), []);
  return {
    open: (at: Point, current: string | null | undefined, onPick: (p: Assignee | null) => void, allowNone = true) => setState({ at, current, allowNone, onPick }),
    node: state && <AssigneePicker siteId={siteId} {...state} onClose={close} />,
  };
}

/** The point just under an element, for popovers opened from a button or the keyboard. */
export function below(el: HTMLElement): Point {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.bottom + 4 };
}

// ---- item controls

/** Tag chips for one item; editors can remove a tag or type a new one. Text only, never HTML. */
export function Tags({ item, canEdit, onChange }: { item: Feedback; canEdit: boolean; onChange: (tags: string[]) => void }) {
  const [draft, setDraft] = useState("");
  if (!canEdit && item.tags.length === 0) return null;
  function add(e: FormEvent) {
    e.preventDefault();
    const tag = slug(draft);
    if (!TAG_PATTERN.test(tag) || item.tags.includes(tag)) return;
    setDraft("");
    onChange([...item.tags, tag]);
  }
  return (
    <div className="tags">
      {item.tags.map((t) => (
        <span key={t} className={canEdit ? "tag" : "tag static"}>
          {t}
          {canEdit && <button type="button" aria-label={`Remove tag ${t}`} onClick={() => onChange(item.tags.filter((x) => x !== t))}>×</button>}
        </span>
      ))}
      {canEdit && (
        <form onSubmit={add}>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add tag…" maxLength={32} aria-label="Add a tag" list="site-tags" />
        </form>
      )}
    </div>
  );
}

/** Internal notes. Viewers read them; editors write; the author or an admin deletes. */
export function Notes({ siteId, itemId, canEdit, canDeleteAny, meId }: {
  siteId: string; itemId: string; canEdit: boolean; canDeleteAny: boolean; meId: string;
}) {
  const base = `/sites/${siteId}/feedback/${itemId}/notes`;
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [body, setBody] = useState("");
  const toast = useToast();
  const [error, setError] = useState("");
  useEffect(() => { api<Note[]>(base).then(setNotes, (e) => setError(e.message)); }, [base]);
  async function add(e: FormEvent) {
    e.preventDefault();
    await toast.attempt(
      api<Note>(base, json("POST", { body })).then((note) => {
        setNotes((cur) => [...(cur ?? []), note]);
        setBody("");
      }),
      "Note added",
    );
  }
  async function remove(id: string) {
    await toast.attempt(
      api(`${base}/${id}`, { method: "DELETE" }).then(() => setNotes((cur) => (cur ?? []).filter((n) => n.id !== id))),
      "Note deleted",
    );
  }
  return (
    <div className="notes">
      <p className="muted">Internal notes. Never shown to the person who sent the feedback.</p>
      {notes?.length === 0 && <p className="muted">No notes yet.</p>}
      <ul>
        {(notes ?? []).map((n) => (
          <li key={n.id}>
            <span className="muted">{n.author_name ?? "Someone who has left"} · {new Date(n.created_at).toLocaleString()}</span>
            {(n.author_id === meId || canDeleteAny) && <button type="button" className="link" onClick={() => remove(n.id)}> Delete</button>}
            <p>{n.body}</p>
          </li>
        ))}
      </ul>
      {error && <p className="error">{error}</p>}
      {canEdit && (
        <form onSubmit={add}>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} placeholder="Add a note…" aria-label="New note" />
          <button disabled={!body.trim()}>Add note</button>
        </form>
      )}
    </div>
  );
}

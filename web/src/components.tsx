import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useOnline } from "./online";
import { api, avatarSrc, displayName, type ConfigSchema, type JsonSchemaProp, type Profile } from "./api";

/** Bottom toast: "offline" while disconnected, then a brief "back online" when it returns. */
export function OfflineBanner() {
  const online = useOnline();
  const [wasOffline, setWasOffline] = useState(false);
  const [showBack, setShowBack] = useState(false);

  useEffect(() => {
    if (!online) {
      setWasOffline(true);
      setShowBack(false);
      return;
    }
    if (!wasOffline) return;
    setShowBack(true);
    const t = setTimeout(() => {
      setShowBack(false);
      setWasOffline(false);
    }, 3000);
    return () => clearTimeout(t);
  }, [online, wasOffline]);

  if (online && !showBack) return null;
  return (
    <div className={`net-toast ${online ? "back" : "off"}`} role="status" aria-live="polite">
      <span className="net-dot" aria-hidden />
      {online ? "Back online" : "You're offline. Changes won't save."}
    </div>
  );
}

/** Brand mark; decorative wherever the "Ganymede" name is next to it. */
export function Logo({ size = 28, className = "" }: { size?: number; className?: string }) {
  return <img className={`logo ${className}`} src="/ganymede-icon.svg" width={size} height={size} alt="" />;
}

export function Avatar({ user, size }: { user: Partial<Profile> & { email: string }; size?: "lg" | "xl" }) {
  const initials =
    ((user.first_name?.[0] ?? "") + (user.last_name?.[0] ?? "")).toUpperCase() || user.email[0].toUpperCase();
  return (
    <span className={`avatar ${size ?? ""}`} aria-hidden>
      {user.avatar_url ? <img src={avatarSrc(user.avatar_url)!} alt="" /> : initials}
    </span>
  );
}

interface Suggestion extends Profile {
  user_id: string;
}

/** Email autocomplete backed by /sites/{id}/user-search. Reports the chosen email via onSelect. */
export function UserPicker({ siteId, value, onSelect }: {
  siteId: string;
  value: string;
  onSelect: (email: string) => void;
}) {
  const [text, setText] = useState(value);
  const [options, setOptions] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [searched, setSearched] = useState(false);
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => setText(value), [value]);

  useEffect(() => {
    const q = text.trim();
    if (q.length < 2 || q === value) {
      setOptions([]);
      setSearched(false);
      return;
    }
    let stale = false;
    const t = setTimeout(() => {
      api<Suggestion[]>(`/sites/${siteId}/user-search?q=${encodeURIComponent(q)}`)
        .then((r) => {
          if (stale) return;
          setOptions(r);
          setSearched(true);
          setActive(-1);
        })
        .catch(() => !stale && setOptions([]));
    }, 200);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [text, siteId, value]);

  useEffect(() => {
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function choose(s: Suggestion) {
    onSelect(s.email);
    setText(s.email);
    setOpen(false);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, options.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && open && active >= 0) {
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="picker" ref={box}>
      <input
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        placeholder="Search by name or email…"
        autoComplete="off"
        value={text}
        onChange={(e) => { setText(e.target.value); onSelect(""); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
      />
      {open && (options.length > 0 || searched) && (
        <ul className="menu" id={listId} role="listbox">
          {options.map((o, i) => (
            <li
              key={o.user_id}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => { e.preventDefault(); choose(o); }}
              onMouseEnter={() => setActive(i)}
            >
              <Avatar user={o} />
              <span className="stack">
                <span>{displayName(o)}</span>
                {displayName(o) !== o.email && <span className="muted">{o.email}</span>}
              </span>
            </li>
          ))}
          {options.length === 0 && <li className="empty">No matching users</li>}
        </ul>
      )}
    </div>
  );
}

/** One input per primitive property of a JSON-schema config model (notification providers, challenge verifiers). */
export function SchemaFields({ schema, values, onChange }: {
  schema: ConfigSchema;
  values: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const props = Object.entries(schema.properties ?? {});
  if (props.length === 0) return null;
  const set = (k: string, v: unknown) => onChange({ ...values, [k]: v });

  return (
    <>
      {props.map(([key, p]: [string, JsonSchemaProp]) => {
        const label = p.title ?? key;
        const value = values[key] ?? p.default ?? "";
        if (p.type === "boolean") {
          return (
            <label key={key} className="inline">
              <input type="checkbox" checked={Boolean(value)} onChange={(e) => set(key, e.target.checked)} /> {label}
            </label>
          );
        }
        if (p.enum) {
          return (
            <label key={key}>{label}
              <select value={String(value)} onChange={(e) => set(key, e.target.value)}>
                {p.enum.map((o) => <option key={o}>{o}</option>)}
              </select>
            </label>
          );
        }
        const numeric = p.type === "integer" || p.type === "number";
        return (
          <label key={key}>{label}
            <input
              type={numeric ? "number" : "text"}
              min={p.minimum}
              max={p.maximum}
              value={String(value)}
              required={schema.required?.includes(key)}
              onChange={(e) => set(key, numeric && e.target.value !== "" ? Number(e.target.value) : e.target.value)}
            />
            {p.description && <small className="muted"> {p.description}</small>}
          </label>
        );
      })}
    </>
  );
}

/**
 * Tab bar that scrolls sideways when it doesn't fit (phones). Keeps the active tab in view when the route
 * changes, and marks which edges have more tabs beyond them (`data-more-start` / `data-more-end`) so CSS can
 * fade them.
 */
export function ScrollTabs({ children }: { children: ReactNode }) {
  const nav = useRef<HTMLElement>(null);
  const { pathname } = useLocation();

  function markEdges() {
    const el = nav.current;
    if (!el) return;
    el.toggleAttribute("data-more-start", el.scrollLeft > 1);
    el.toggleAttribute("data-more-end", el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  }

  useEffect(() => {
    const el = nav.current;
    if (!el) return;
    markEdges();
    const ro = new ResizeObserver(markEdges);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = nav.current;
    const active = el?.querySelector<HTMLElement>("a.active");
    if (!el || !active) return;
    const box = el.getBoundingClientRect();
    const tab = active.getBoundingClientRect();
    // Centre the active tab, clamped by the browser to the scrollable range.
    const left = el.scrollLeft + tab.left - box.left - (box.width - tab.width) / 2;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ left, behavior: calm ? "auto" : "smooth" });
    markEdges();
  }, [pathname]);

  return <nav className="tabs" ref={nav} onScroll={markEdges}>{children}</nav>;
}

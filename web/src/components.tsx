import { useEffect, useId, useRef, useState } from "react";
import { api, avatarSrc, displayName, type Profile } from "./api";

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

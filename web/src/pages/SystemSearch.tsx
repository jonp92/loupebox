import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { SystemSetting } from "../api";
import { EmptyState } from "../ui/EmptyState";
import { Badge } from "../ui/Badge";
import { Status } from "../ui/Status";
import { tabFor } from "./systemTabs";

/** Quick views over the same list: what was changed here, what still needs a value, what only .env can change. */
export const FILTERS = {
  overridden: { label: "Changed in UI", test: (s: SystemSetting) => s.source === "ui" },
  unset: { label: "Not set", test: (s: SystemSetting) => s.secret && !s.configured },
  readonly: { label: "Only in .env", test: (s: SystemSetting) => !s.editable },
} as const;
export type FilterKey = keyof typeof FILTERS;

/** Every word of the query must appear in the label, help, group or key (so `smtp_host` and `SMTP HOST` both work). */
export function matchSettings(items: SystemSetting[], query: string, filter: FilterKey | null): SystemSetting[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return items.filter((s) => {
    if (filter && !FILTERS[filter].test(s)) return false;
    const hay = `${s.label} ${s.help} ${s.group} ${s.key} ${s.key.replace(/_/g, " ")}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

export const isSearching = (query: string, filter: FilterKey | null) => query.trim() !== "" || filter !== null;

/** The search box and quick filters. `/` focuses the box, Escape clears it. */
export function SettingsSearchBar({ query, filter, onQuery, onFilter }: {
  query: string; filter: FilterKey | null; onQuery: (q: string) => void; onFilter: (f: FilterKey | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || t.closest("input, textarea, select, [contenteditable]")) return;
      e.preventDefault();
      input.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <div className="toolbar">
        <input
          ref={input}
          type="search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && onQuery("")}
          placeholder="Search settings, e.g. smtp or retention"
          aria-label="Search settings"
          maxLength={100}
        />
      </div>
      <div className="filter-toggles" role="group" aria-label="Show only">
        {(Object.keys(FILTERS) as FilterKey[]).map((k) => (
          <button key={k} type="button" className="filter-toggle" aria-pressed={filter === k} onClick={() => onFilter(filter === k ? null : k)}>
            {FILTERS[k].label}
          </button>
        ))}
      </div>
    </>
  );
}

/** Flat list of matches; each row links to the setting on its tab. */
export function SettingsResults({ results, onPick }: { results: SystemSetting[]; onPick: () => void }) {
  const count = `${results.length} ${results.length === 1 ? "setting matches" : "settings match"}`;
  return (
    <>
      <p className="sr-only" role="status">{results.length === 0 ? "" : count}</p>
      {results.length === 0 ? (
        <EmptyState>No settings match.</EmptyState>
      ) : (
        <ul className="ruled">
          {results.map((s) => {
            const tab = tabFor(s.group);
            return tab && (
              <li key={s.key}>
                <Link className="ruled-link" to={`/system/${tab.path}#setting-${s.key}`} onClick={onPick}>
                  <span className="ruled-main">
                    <span className="ruled-title">{s.label}</span>
                    <span className="check-detail">{tab.label} › {s.group}</span>
                  </span>
                  <span className="ruled-side">
                    {s.source === "ui" && <Badge tone="brass">Override</Badge>}
                    {s.secret && <Status tone={s.configured ? "ok" : "muted"}>{s.configured ? "Set" : "Not set"}</Status>}
                    {!s.editable && <Badge tone="brass">.env</Badge>}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

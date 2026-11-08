import type { ReactNode } from "react";

export type StatusTone = "ok" | "danger" | "muted" | "unread" | "read" | "archived";

const GEM = "M6 1L11 5 6 11 1 5z";

/** A mark plus a text label, never color alone. Amber (unread) is for unread feedback and nothing else. */
export function Status({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <span className={`status status-${tone}`}>
      <svg className="status-mark" width="12" height="12" viewBox="0 0 12 12" aria-hidden focusable="false">
        {tone === "unread" && <path d={GEM} fill="currentColor" />}
        {tone === "read" && <path d={GEM} fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" />}
        {tone === "archived" && <path d="M1.5 2.5h9v2h-9zM2.5 4.5v5h7v-5M5 7h2" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" />}
        {(tone === "ok" || tone === "danger") && <circle cx="6" cy="6" r="3" fill="currentColor" />}
        {tone === "muted" && <circle cx="6" cy="6" r="2.6" fill="none" stroke="currentColor" strokeWidth="1.25" />}
      </svg>
      <span className="status-label">{children}</span>
    </span>
  );
}

import type { ReactNode } from "react";

/** A calm, specific sentence with a hollow gem and a CLEAR tag. No illustration. */
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="empty-state" role="status">
      <svg className="empty-gem" width="28" height="28" viewBox="0 0 12 12" aria-hidden focusable="false">
        <path d="M6 1L11 5 6 11 1 5zM1 5h10" fill="none" stroke="currentColor" strokeWidth=".7" strokeLinejoin="round" />
      </svg>
      <p>{children}</p>
      <span className="badge badge-brass">Clear</span>
    </div>
  );
}

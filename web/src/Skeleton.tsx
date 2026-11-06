import type { ReactNode } from "react";

/** Holds a page's place while its first request is in flight. Screen readers hear `label`; the shapes are hidden. */
export function Placeholder({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div aria-busy="true">
      <p className="sr-only" role="status">{label}</p>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}

/** One grey bar; `w` and `h` are CSS lengths. */
export function Bar({ w = "100%", h = "1rem" }: { w?: string; h?: string }) {
  return <span className="skeleton" style={{ width: w, height: h }} />;
}

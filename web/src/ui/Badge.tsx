import type { ReactNode } from "react";

/** An outlined mono label for roles, tags and kinds. Brass is for identity (Superadmin, an overridden setting). */
export function Badge({ tone = "muted", plain, title, children }: {
  tone?: "muted" | "brass"; plain?: boolean; title?: string; children: ReactNode;
}) {
  return <span className={`badge badge-${tone}${plain ? " badge-plain" : ""}`} title={title}>{children}</span>;
}

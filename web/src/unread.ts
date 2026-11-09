import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useLive } from "./live";

/** A count that may have stopped at the server's cap: "10,000+". */
export const fmtCount = (n: number, capped: boolean) => `${n.toLocaleString()}${capped ? "+" : ""}`;

export interface Unread {
  count: number;
  capped: boolean;
}

/**
 * How many items are unread across every site the user can see, kept current by the live stream. While
 * there are some, the tab title says so ("(3) Loupebox Feedback") and an installed app gets a badge.
 * `enabled` is false while signed out.
 */
export function useUnread(enabled: boolean): Unread | null {
  const [unread, setUnread] = useState<Unread | null>(null);
  const latest = useRef(0); // only the newest request sets the number
  const load = useCallback(() => {
    const mine = ++latest.current;
    api<{ unread?: number; unread_capped?: boolean }>("/inbox/counts").then(
      (c) => mine === latest.current && setUnread({ count: c.unread ?? 0, capped: Boolean(c.unread_capped) }),
      () => undefined, // keep the last number; the next event or visit tries again
    );
  }, []);
  useEffect(() => {
    if (enabled) load();
    else setUnread(null);
  }, [enabled, load]);
  useLive(() => enabled && load(), undefined, { hidden: true }); // a background tab is where the title matters

  const count = unread?.count ?? 0;
  useEffect(() => {
    const base = document.title.replace(/^\(\d[\d,]*\+?\) /, "");
    document.title = count > 0 ? `(${fmtCount(count, Boolean(unread?.capped))}) ${base}` : base;
    try {
      void (count > 0 ? navigator.setAppBadge?.(count) : navigator.clearAppBadge?.());
    } catch {
      /* not an installed app, or the browser has no badge */
    }
    return () => {
      document.title = base;
    };
  }, [count, unread?.capped]);
  return unread;
}

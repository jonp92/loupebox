import { useEffect, useRef } from "react";
import { openStream } from "./api";

/** What the server says changed. Ids only: the page refetches what it shows. */
export interface LiveEvent {
  kind: "feedback" | "thread" | "resync";
  site_id: string;
  feedback_id: string | null;
}

const listeners = new Set<(e: LiveEvent) => void>();
const emit = (e: LiveEvent) => listeners.forEach((fn) => fn(e));
const RESYNC: LiveEvent = { kind: "resync", site_id: "", feedback_id: null };

/** Read one stream until it ends. Resolves on a clean end (the server closes it when the token expires). */
async function read(signal: AbortSignal, onOpen: () => void) {
  const res = await openStream("/events", signal);
  onOpen();
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = frame.split("\n").find((line) => line.startsWith("data: "));
      if (data) emit(JSON.parse(data.slice(6)));
    }
  }
}

/**
 * Keep the event stream open while signed in. A clean end reconnects at once (the next request carries a
 * fresh token); a failure retries with a growing delay, and every page refetches once it is back, since
 * events may have been missed. Returns the stop function.
 */
export function startLive(): () => void {
  const stop = new AbortController();
  const onVisible = () => !document.hidden && emit(RESYNC); // a hidden tab may have been throttled
  document.addEventListener("visibilitychange", onVisible);
  (async () => {
    let delay = 1000;
    let lostEvents = false;
    while (!stop.signal.aborted) {
      try {
        await read(stop.signal, () => {
          delay = 1000;
          if (lostEvents) emit(RESYNC);
          lostEvents = false;
        });
        await new Promise((resolve) => setTimeout(resolve, 1000)); // never a tight loop if a stream ends at once
      } catch {
        if (stop.signal.aborted) return;
        lostEvents = true;
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(delay * 2, 30000);
      }
    }
  })();
  return () => {
    stop.abort();
    document.removeEventListener("visibilitychange", onVisible);
  };
}

/** Call `onEvent` (once per burst) when something the page may show changed. Pass `match` to ignore the rest. */
export function useLive(onEvent: (e: LiveEvent) => void, match?: (e: LiveEvent) => boolean) {
  const latest = useRef({ onEvent, match });
  latest.current = { onEvent, match };
  useEffect(() => {
    let timer: number | undefined;
    const fn = (e: LiveEvent) => {
      if (document.hidden) return; // the resync when the tab is shown again catches it up
      if (e.kind !== "resync" && latest.current.match && !latest.current.match(e)) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => latest.current.onEvent(e), 300); // a bulk action sends many
    };
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
      window.clearTimeout(timer);
    };
  }, []);
}

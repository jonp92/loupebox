/** Small stroke icons, built with the DOM (never from strings) so nothing here can inject markup. */

const PATHS: Record<string, string[]> = {
  chat: ["M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.3A8 8 0 1 1 21 12z"],
  close: ["M6 6l12 12", "M18 6L6 18"],
  bug: ["M8 9h8v5a4 4 0 0 1-8 0V9z", "M9.5 9a2.5 2.5 0 0 1 5 0", "M4 13h4", "M16 13h4", "M5 6l3 3", "M19 6l-3 3", "M5 20l3-3.5", "M19 20l-3-3.5"],
  idea: ["M9 18h6", "M10 21h4", "M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.3 1 2.1h5c0-.8.4-1.6 1-2.1A6 6 0 0 0 12 3z"],
  question: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4", "M12 17.5h.01"],
  image: ["M4 5h16v14H4z", "M4 16l4.5-4.5 4 4 3-3L20 17", "M9 9.5h.01"],
  praise: ["M12 21s-7-4.4-9.3-9A5.2 5.2 0 0 1 12 6.6 5.2 5.2 0 0 1 21.3 12C19 16.6 12 21 12 21z"],
};

const NS = "http://www.w3.org/2000/svg";

/** An icon by name, or `null` when there is none (callers then fall back to a text icon). */
export function icon(name: string): SVGElement | null {
  const paths = PATHS[name];
  if (!paths) return null;
  const svg = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({
    viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor",
    "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false",
  })) svg.setAttribute(k, v);
  for (const d of paths) {
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

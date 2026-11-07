/** Small DOM helper shared by the widget's modules. */

export type Child = Node | string | null | false | undefined;

/**
 * Build an element. Attributes are plain strings; `style` and `on*` attributes are refused so nothing
 * here can create inline styles (blocked by strict page CSPs) or inline handlers.
 */
export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | boolean | undefined> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === false) continue;
    if (name === "style" || name.startsWith("on")) throw new Error(`refusing "${name}" attribute`);
    if (name === "class") el.className = String(value);
    else el.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children) if (child) el.append(child);
  return el;
}

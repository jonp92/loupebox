import { label, safeHref } from "./triage";

const BADGED = "issue_type"; // already the type badge on the card
const TECHNICAL = "widget_version"; // shown last and quieter

function Value({ value }: { value: unknown }) {
  if (typeof value === "boolean") {
    // A mark plus a word: never color alone.
    return <><span aria-hidden="true">{value ? "✓" : "✗"}</span> {value ? "Yes" : "No"}</>;
  }
  if (value === null || value === "") return <span className="meta-empty">(empty)</span>;
  const text = String(value);
  const href = typeof value === "string" ? safeHref(value) : null;
  // Rendered as text by React; only http(s) values become links.
  return href ? <a href={href} target="_blank" rel="noopener noreferrer">{text}</a> : <>{text}</>;
}

/** What the visitor's page sent along with the feedback, as labelled rows instead of a JSON block. Values in
 * `metadata` are always scalars, so a plain list shows all of it. */
export function MetadataList({ metadata }: { metadata: Record<string, unknown> }) {
  const type = metadata[BADGED];
  const badged = typeof type === "string" && /^[a-z0-9_-]{1,32}$/.test(type);
  const keys = Object.keys(metadata).filter((k) => !(badged && k === BADGED));
  if (!keys.length) return null;
  keys.sort((a, b) => Number(a === TECHNICAL) - Number(b === TECHNICAL)); // stable: the rest keep their order
  return (
    <dl className="meta" aria-label="Details sent with this feedback">
      {keys.map((k) => (
        <div key={k} className={k === TECHNICAL ? "meta-tech" : undefined}>
          <dt title={k}>{label(k)}</dt>
          <dd><Value value={metadata[k]} /></dd>
        </div>
      ))}
    </dl>
  );
}

import type { CustomField } from "./api";
import { answerText, answered } from "./fields";
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

function Rows({ keys, metadata, labelOf }: { keys: string[]; metadata: Record<string, unknown>; labelOf: (key: string) => string }) {
  return (
    <>
      {keys.map((k) => (
        <div key={k} className={k === TECHNICAL ? "meta-tech" : undefined}>
          <dt title={k}>{labelOf(k)}</dt>
          <dd><Value value={metadata[k]} /></dd>
        </div>
      ))}
    </>
  );
}

/** What the visitor's page sent along with the feedback, as labelled rows instead of a JSON block. Values in
 * `metadata` are always scalars, so a plain list shows all of it. The site's own fields come first with their
 * labels; everything else (what the page sent, the widget version, answers to fields since deleted) is below. */
export function MetadataList({ metadata, fields = [] }: { metadata: Record<string, unknown>; fields?: CustomField[] }) {
  const type = metadata[BADGED];
  const badged = typeof type === "string" && /^[a-z0-9_-]{1,32}$/.test(type);
  const defined = fields.filter((f) => answered(metadata, f));
  const known = new Set(fields.map((f) => f.id));
  const rest = Object.keys(metadata).filter((k) => !known.has(k) && !(badged && k === BADGED));
  rest.sort((a, b) => Number(a === TECHNICAL) - Number(b === TECHNICAL)); // stable: the rest keep their order
  if (!defined.length && !rest.length) return null;
  const byId = new Map(fields.map((f) => [f.id, f]));
  const shown = { ...metadata, ...Object.fromEntries(defined.map((f) => [f.id, f.type === "select" ? answerText(f, metadata[f.id]) : metadata[f.id]])) };
  return (
    <>
      {defined.length > 0 && (
        <dl className="meta" aria-label="Answers to the site's questions">
          <Rows keys={defined.map((f) => f.id)} metadata={shown} labelOf={(k) => byId.get(k)!.label} />
        </dl>
      )}
      {rest.length > 0 && (defined.length > 0 ? (
        <details className="meta-more">
          <summary>Other data ({rest.length})</summary>
          <dl className="meta" aria-label="Other details sent with this feedback"><Rows keys={rest} metadata={metadata} labelOf={label} /></dl>
        </details>
      ) : (
        <dl className="meta" aria-label="Details sent with this feedback"><Rows keys={rest} metadata={metadata} labelOf={label} /></dl>
      ))}
    </>
  );
}

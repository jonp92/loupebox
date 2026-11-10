import { useState, type FormEvent } from "react";
import { api, json, type CustomField, type Site } from "../api";
import { useConfirm } from "../confirm";
import { Icon } from "../icons";
import { useToast } from "../toast";
import { label } from "../triage";
import { Badge } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";
import { Sheet } from "../ui/Sheet";

// The server enforces all of these; they are repeated here so a mistake shows before the round trip.
const FIELD_ID = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const LOCALE = /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;
const RESERVED = ["issue_type", "widget_version", "locale"];
const MAX_FIELDS = 10;
const MAX_OPTIONS = 20;
const MAX_LOCALES = 8;
const MAX_IN_LIST = 2;

const idFrom = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 32);

/** An option being edited. `value` is what is stored: fixed once saved, taken from the label for a new one. */
interface Row { key: number; value: string | null; label: string }
interface Tr { label: string; options: Record<number, string> } // option answers keyed by Row.key
let nextKey = 1;
const valueOf = (r: Row) => r.value ?? r.label.trim().slice(0, 64);

function FieldForm({ field, fields, onSave, onCancel }: {
  field?: CustomField; fields: CustomField[]; onSave: (f: CustomField) => Promise<void>; onCancel: () => void;
}) {
  const [text, setText] = useState(field?.label ?? "");
  const [id, setId] = useState(field?.id ?? "");
  const [idTouched, setIdTouched] = useState(false);
  const [type, setType] = useState<CustomField["type"]>(field?.type ?? "select");
  const [required, setRequired] = useState(field?.required ?? false);
  const [showInList, setShowInList] = useState(field?.show_in_list ?? false);
  const [maxLength, setMaxLength] = useState(field?.max_length ? String(field.max_length) : "");
  const [rows, setRows] = useState<Row[]>(() => (field?.options ?? []).map((o) => ({ key: nextKey++, value: o.value, label: o.label })));
  const [tr, setTr] = useState<Record<string, Tr>>(() => Object.fromEntries(
    Object.entries(field?.translations ?? {}).map(([code, t]) => [code, {
      label: t.label ?? "",
      options: Object.fromEntries(rows.flatMap((r) => (r.value !== null && t.options[r.value] ? [[r.key, t.options[r.value]]] : []))),
    }]),
  ));
  const [newLocale, setNewLocale] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const others = fields.filter((f) => f.id !== field?.id);
  const inListFull = others.filter((f) => f.show_in_list).length >= MAX_IN_LIST;
  const usedLocales = new Set([...others.flatMap((f) => Object.keys(f.translations)), ...Object.keys(tr)]);
  const named = rows.filter((r) => r.label.trim());

  const setRow = (key: number, patch: Partial<Row>) => setRows(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const setTrans = (code: string, patch: Partial<Tr>) => setTr({ ...tr, [code]: { ...tr[code], ...patch } });

  function addLocale() {
    const code = newLocale.trim();
    if (!LOCALE.test(code)) return setError(`"${code}" is not a language code such as de or pt-BR.`);
    if (!tr[code] && usedLocales.size >= MAX_LOCALES) return setError(`A site can have at most ${MAX_LOCALES} languages.`);
    setError("");
    if (!tr[code]) setTr({ ...tr, [code]: { label: "", options: {} } });
    setNewLocale("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const fieldId = field?.id ?? id;
    const options = type === "select" ? named.map((r) => ({ value: valueOf(r), label: r.label.trim() })) : [];
    const problem =
      (!FIELD_ID.test(fieldId) && "The id needs 1 to 32 characters: a-z, 0-9, - or _.") ||
      (RESERVED.includes(fieldId) && `"${fieldId}" is reserved.`) ||
      (!field && others.some((f) => f.id === fieldId) && "Another field already uses that id.") ||
      (type === "select" && !options.length && "Add at least one option.") ||
      (new Set(options.map((o) => o.value)).size !== options.length && "Two options are the same.") ||
      (showInList && inListFull && `At most ${MAX_IN_LIST} fields can show in the list.`);
    if (problem) return setError(problem);

    const translations: CustomField["translations"] = {};
    for (const [code, t] of Object.entries(tr)) {
      const answers = Object.fromEntries(named.flatMap((r) => (t.options[r.key]?.trim() ? [[valueOf(r), t.options[r.key].trim()]] : [])));
      if (t.label.trim() || Object.keys(answers).length) translations[code] = { ...(t.label.trim() && { label: t.label.trim() }), options: answers };
    }
    setBusy(true);
    try {
      await onSave({
        id: fieldId, type, label: text.trim(), required, options, translations,
        max_length: type === "text" && maxLength ? Number(maxLength) : null,
        show_in_list: showInList,
      });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <label>Question<input value={text} maxLength={80} required
        onChange={(e) => { setText(e.target.value); if (!field && !idTouched) setId(idFrom(e.target.value)); }} /></label>
      <label>Type
        <select value={type} disabled={!!field} onChange={(e) => setType(e.target.value as CustomField["type"])} aria-describedby="cf-locked">
          <option value="select">Choose one (select)</option>
          <option value="checkbox">Yes or no (checkbox)</option>
          <option value="text">Short text</option>
        </select>
      </label>
      <label>Id<input value={field?.id ?? id} disabled={!!field} maxLength={32} required spellCheck={false}
        onChange={(e) => { setId(e.target.value); setIdTouched(true); }} aria-describedby="cf-locked" /></label>
      <p id="cf-locked" className="muted hint">
        The id is the key the answer is stored under, and the type decides how it is read.{" "}
        {field ? "Neither can change after the field is created." : "Neither can be changed later."}
      </p>

      {type === "select" && (
        <fieldset>
          <legend>Options</legend>
          {rows.map((r) => (
            <div key={r.key} className="option-row">
              <input value={r.label} maxLength={64} aria-label="Option" onChange={(e) => setRow(r.key, { label: e.target.value })} />
              <button type="button" className="icon" aria-label={`Remove option ${r.label}`} onClick={() => setRows(rows.filter((x) => x.key !== r.key))}><Icon name="trash" /></button>
            </div>
          ))}
          <button type="button" disabled={rows.length >= MAX_OPTIONS} onClick={() => setRows([...rows, { key: nextKey++, value: null, label: "" }])}>
            <Icon name="plus" size={18} />Add option
          </button>
          {field && <p className="muted hint">Renaming an option changes what visitors read, not what is stored.</p>}
        </fieldset>
      )}
      {type === "text" && (
        <label>Longest answer<small> (characters, up to 256)</small>
          <input type="number" min={1} max={256} value={maxLength} placeholder="256" onChange={(e) => setMaxLength(e.target.value)} />
        </label>
      )}

      <label className="inline"><input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
        {type === "checkbox" ? "Must be ticked to send" : "Required"}</label>
      <label className="inline"><input type="checkbox" checked={showInList} disabled={inListFull && !field?.show_in_list} onChange={(e) => setShowInList(e.target.checked)} />
        Show the answer on feedback rows</label>

      <h3 className="section-title">Translations</h3>
      <p className="muted hint">
        Visitors whose page language matches see these instead of the text above. Anything left blank falls back to it, and what is stored never changes.
      </p>
      {Object.keys(tr).map((code) => (
        <fieldset key={code} className="translation">
          <legend>{code}</legend>
          <label>Question<input lang={code} value={tr[code].label} placeholder={text} maxLength={80} onChange={(e) => setTrans(code, { label: e.target.value })} /></label>
          {type === "select" && named.map((r) => (
            <label key={r.key}>Option: {r.label}
              <input lang={code} value={tr[code].options[r.key] ?? ""} placeholder={r.label} maxLength={64}
                onChange={(e) => setTrans(code, { options: { ...tr[code].options, [r.key]: e.target.value } })} />
            </label>
          ))}
          <button type="button" className="danger" onClick={() => setTr(Object.fromEntries(Object.entries(tr).filter(([c]) => c !== code)))}>Remove {code}</button>
        </fieldset>
      ))}
      <div className="option-row">
        <input value={newLocale} placeholder="de, pt-BR" aria-label="Language code" lang="en" autoCapitalize="none" spellCheck={false}
          onChange={(e) => setNewLocale(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLocale(); } }} />
        <button type="button" onClick={addLocale} disabled={!newLocale.trim()}>Add language</button>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="row-actions">
        <button type="button" onClick={onCancel}>Cancel</button>
        <button className="primary" disabled={busy || !text.trim()}>{field ? "Save" : "Add field"}</button>
      </div>
    </form>
  );
}

/** The questions the site's feedback form asks besides the message. The list is saved whole on every change. */
export default function CustomFields({ site, onChange }: { site: Site; onChange: (s: Site) => void }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  const fields = site.custom_fields;

  const save = (next: CustomField[]) => api<Site>(`/sites/${site.id}`, json("PATCH", { custom_fields: next })).then(onChange);
  async function change(next: CustomField[], ok: string) {
    setBusy(true);
    await toast.attempt(save(next), ok);
    setBusy(false);
  }
  const move = (i: number, by: -1 | 1) => {
    const next = [...fields];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    return change(next, "Order saved");
  };
  async function remove(f: CustomField) {
    if (!(await confirm({ title: `Delete "${f.label}"?`, message: "Visitors stop being asked. Answers already collected stay with each feedback.", confirmLabel: "Delete", danger: true }))) return;
    await change(fields.filter((x) => x.id !== f.id), "Field deleted");
  }
  async function saveField(f: CustomField) {
    await save(editing === "new" ? [...fields, f] : fields.map((x) => (x.id === f.id ? f : x)));
    toast.success("Field saved");
    setEditing(null);
  }

  return (
    <section className="panel" id="custom-fields">
      <div className="section-head">
        <h2>Custom fields <span className="count">{fields.length}</span></h2>
        <button className="primary" onClick={() => setEditing("new")} disabled={fields.length >= MAX_FIELDS}><Icon name="plus" size={18} />Add field</button>
      </div>
      <p className="muted hint">
        Questions the feedback form asks besides the message: a choice, a yes or no, or a few words. Answers are stored with each feedback, can be filtered on, and are exported. The widget shows them automatically.
      </p>
      <Sheet open={editing !== null} title={editing === "new" ? "Add field" : "Edit field"} onClose={() => setEditing(null)}>
        <FieldForm field={fields.find((f) => f.id === editing)} fields={fields} onSave={saveField} onCancel={() => setEditing(null)} />
      </Sheet>
      {fields.length === 0 ? (
        <EmptyState>No custom fields. Add one to ask visitors for their plan, app version or anything else you triage by.</EmptyState>
      ) : (
        <ul className="ruled" aria-busy={busy}>
          {fields.map((f, i) => (
            <li key={f.id} className="channel-row">
              <span className="ruled-main-col">
                <strong className="ruled-title">{f.label}</strong>
                <span className="channel-meta">
                  <Badge>{label(f.type)}</Badge>
                  {f.required && <Badge>required</Badge>}
                  {f.show_in_list && <Badge>in list</Badge>}
                  <span className="muted check-detail">
                    {f.id}{f.type === "select" && ` · ${f.options.length} options`}
                    {Object.keys(f.translations).length > 0 && ` · ${Object.keys(f.translations).join(", ")}`}
                  </span>
                </span>
              </span>
              <span className="row-actions">
                <button className="icon" aria-label={`Move ${f.label} up`} disabled={busy || i === 0} onClick={() => move(i, -1)}><span className="flip"><Icon name="caret" /></span></button>
                <button className="icon" aria-label={`Move ${f.label} down`} disabled={busy || i === fields.length - 1} onClick={() => move(i, 1)}><Icon name="caret" /></button>
                <button onClick={() => setEditing(f.id)}>Edit</button>
                <button className="danger" disabled={busy} onClick={() => remove(f)}>Delete</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

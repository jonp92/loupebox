import { useState, type FormEvent } from "react";
import type { CustomField } from "./api";
import { answerText } from "./fields";
import { Sheet } from "./ui/Sheet";

/** The wanted answer per field id, as sent in `cf=<id>:<value>`. A field that is not here is not filtered on. */
export type FieldValues = Record<string, string>;

/** One removable chip per active field filter. */
export function fieldChips(fields: CustomField[], values: FieldValues): { id: string; text: string }[] {
  return fields.flatMap((f) => {
    const v = values[f.id];
    if (!v) return [];
    const text = f.type === "text" ? `${f.label} contains "${v}"` : `${f.label}: ${answerText(f, f.type === "checkbox" ? v === "true" : v)}`;
    return [{ id: f.id, text }];
  });
}

function Form({ fields, values, onApply, onCancel }: { fields: CustomField[]; values: FieldValues; onApply: (v: FieldValues) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState<FieldValues>(values);
  const set = (id: string, v: string) => setDraft({ ...draft, [id]: v });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onApply(Object.fromEntries(Object.entries(draft).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()])));
  };
  return (
    <form onSubmit={submit}>
      {fields.map((f) => (
        <label key={f.id}>{f.label}
          {f.type === "text" ? (
            <input value={draft[f.id] ?? ""} maxLength={256} placeholder="Contains…" onChange={(e) => set(f.id, e.target.value)} />
          ) : (
            <select value={draft[f.id] ?? ""} onChange={(e) => set(f.id, e.target.value)}>
              <option value="">Any</option>
              {f.type === "checkbox"
                ? <><option value="true">Yes</option><option value="false">No</option></>
                : f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
        </label>
      ))}
      <div className="row-actions">
        <button type="button" onClick={() => setDraft({})}>Clear all</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        <button className="primary">Apply</button>
      </div>
    </form>
  );
}

/** The site's custom fields as filters, in one sheet so the filter bar stays short. */
export function FieldFilterSheet({ open, fields, values, onApply, onClose }: {
  open: boolean; fields: CustomField[]; values: FieldValues; onApply: (v: FieldValues) => void; onClose: () => void;
}) {
  return (
    <Sheet open={open} title="Filter by fields" onClose={onClose}>
      <Form fields={fields} values={values} onApply={(v) => { onApply(v); onClose(); }} onCancel={onClose} />
    </Sheet>
  );
}

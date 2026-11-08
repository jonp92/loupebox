import { useEffect, useState, type FormEvent } from "react";
import { NavLink, Navigate, useParams } from "react-router-dom";
import { api, json, type SystemSetting } from "../api";
import { useAuth } from "../auth";
import { ScrollTabs } from "../components";
import SystemHealth from "./SystemHealth";
import SystemStorage from "./SystemStorage";
import SystemTestEmail from "./SystemTestEmail";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";
import { Bar, Placeholder } from "../Skeleton";
import { Badge } from "../ui/Badge";
import { Status } from "../ui/Status";

type Draft = Record<string, string | boolean>;

const envName = (key: string) => key.toUpperCase();
const shown = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v === "" || v == null ? "(empty)" : String(v));

/** Tabs in display order: URL segment, label and the setting groups each one shows. */
const TABS = [
  { path: "status", label: "Status", groups: ["Server"] },
  { path: "email", label: "Email & notifications", groups: ["Email", "Inbound email", "Notifications"] },
  { path: "form", label: "Public form", groups: ["Public feedback form"] },
  { path: "storage", label: "Image storage", groups: ["Image storage"] },
  { path: "accounts", label: "Accounts & limits", groups: ["Sign-in and accounts", "Replies and data"] },
] as const;

/** Words for the values of a setting that has a fixed list of choices (the stored values stay as they are). */
const CHOICE_LABELS: Record<string, Record<string, string>> = {
  storage_backend: { local: "This server's disk", s3: "S3 bucket (or compatible)" },
};

function byGroup(items: SystemSetting[]): [string, SystemSetting[]][] {
  const groups = new Map<string, SystemSetting[]>();
  for (const s of items) groups.set(s.group, [...(groups.get(s.group) ?? []), s]);
  return [...groups];
}

/** Where the value comes from, and a way back to the .env value when it was set here. */
function Source({ s, onReset }: { s: SystemSetting; onReset: () => void }) {
  const env = <code>{envName(s.key)}</code>;
  if (s.source !== "ui") {
    return <p className="setting-source muted"><span>{s.source === "env" ? "From .env" : "Default"} ({env})</span></p>;
  }
  return (
    <p className="setting-source muted">
      <Badge tone="brass">Override</Badge>
      {!s.secret && <span>.env value: {shown(s.env_value)}</span>}
      <button type="button" className="link" onClick={onReset} aria-label={`Reset ${s.label} to the .env value`}>
        Reset
      </button>
    </p>
  );
}

function Field({ s, draft, setDraft }: { s: SystemSetting; draft: Draft; setDraft: (key: string, v: string | boolean) => void }) {
  const id = `setting-${s.key}`;
  const helpId = s.help ? `${id}-help` : undefined;
  const value = draft[s.key] ?? s.value;
  if (s.type === "boolean") {
    return (
      <label className="inline">
        <input id={id} type="checkbox" checked={Boolean(value)} aria-describedby={helpId} onChange={(e) => setDraft(s.key, e.target.checked)} />
        {s.label}
      </label>
    );
  }
  const common = { id, "aria-describedby": helpId };
  return (
    <>
      <label htmlFor={id}>
        {s.label}
        {s.secret && <Status tone={s.configured ? "ok" : "muted"}>{s.configured ? "Set" : "Not set"}</Status>}
      </label>
      {s.choices ? (
        <select {...common} value={String(value)} onChange={(e) => setDraft(s.key, e.target.value)}>
          {s.choices.map((c) => <option key={c} value={c}>{CHOICE_LABELS[s.key]?.[c] ?? (c || "(first configured)")}</option>)}
        </select>
      ) : s.secret ? (
        <input
          {...common}
          type="password"
          autoComplete="new-password"
          placeholder={s.configured ? "Enter a new value to replace it" : "Enter a value"}
          value={String(draft[s.key] ?? "")}
          onChange={(e) => setDraft(s.key, e.target.value)}
        />
      ) : (
        <input
          {...common}
          type={s.type === "integer" ? "number" : "text"}
          min={s.minimum ?? undefined}
          max={s.maximum ?? undefined}
          required={s.type === "integer"}
          value={String(value)}
          onChange={(e) => setDraft(s.key, e.target.value)}
        />
      )}
      {s.help && <p id={helpId} className="hint muted">{s.help}</p>}
    </>
  );
}

export default function SystemSettings() {
  const { me } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
  const [items, setItems] = useState<SystemSetting[] | null>(null);
  const [draft, setDraftState] = useState<Draft>({});
  const [error, setError] = useState("");
  const { tab: tabPath } = useParams();
  useEffect(() => {
    api<SystemSetting[]>("/settings").then(setItems).catch((e) => setError(e.message));
  }, []);

  if (!me?.is_superadmin) return <Navigate to="/" replace />;
  const tab = TABS.find((t) => t.path === tabPath);
  if (!tab) return <Navigate to={`/system/${TABS[0].path}`} replace />;

  const setDraft = (key: string, v: string | boolean) => setDraftState((d) => ({ ...d, [key]: v }));

  const save = (changes: Record<string, unknown>, ok: string) =>
    toast.attempt(
      api<SystemSetting[]>("/settings", json("PATCH", { changes })).then((next) => {
        setItems(next);
        setDraftState((d) => Object.fromEntries(Object.entries(d).filter(([k]) => !(k in changes))));
      }),
      ok,
    );

  function submit(e: FormEvent<HTMLFormElement>, fields: SystemSetting[]) {
    e.preventDefault();
    const changed = fields.filter((s) => s.key in draft && !(s.secret && draft[s.key] === ""));
    if (changed.length === 0) return toast.info("Nothing to save");
    save(Object.fromEntries(changed.map((s) => [s.key, s.type === "integer" ? Number(draft[s.key]) : draft[s.key]])), "Settings saved");
  }

  async function reset(s: SystemSetting) {
    const ok = await confirm({
      title: `Reset ${s.label}?`,
      message: s.secret
        ? "The saved value is deleted. The one in .env is used again, if there is one."
        : `It goes back to the .env value: ${shown(s.env_value)}.`,
      confirmLabel: "Reset",
      danger: s.secret,
    });
    if (ok) save({ [s.key]: null }, `${s.label} reset`);
  }

  return (
    <>
      <div className="page-head"><h1>System settings</h1></div>
      <p className="muted">
        Values saved here win over <code>.env</code> and take effect without a restart. Passwords and keys are
        stored encrypted and can't be read back.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      {!items && !error && (
        <Placeholder label="Loading the settings">
          <div className="ph"><Bar w="12rem" h="1.2rem" /><Bar w="100%" h="2.75rem" /><Bar w="100%" h="2.75rem" /></div>
        </Placeholder>
      )}
      <ScrollTabs>
        {TABS.map((t) => <NavLink key={t.path} to={`/system/${t.path}`}>{t.label}</NavLink>)}
      </ScrollTabs>
      {tab.path === "status" && <SystemHealth />}
      {items && byGroup(items).filter(([group]) => (tab.groups as readonly string[]).includes(group)).map(([group, fields]) =>
        fields.some((s) => s.editable) ? (
          <form key={group} className="panel system-settings" onSubmit={(e) => submit(e, fields)} aria-labelledby={`group-${group}`}>
            <h2 id={`group-${group}`}>{group}</h2>
            {fields.filter((s) => !s.show_when || String(draft[s.show_when.key] ?? items.find((i) => i.key === s.show_when!.key)?.value) === s.show_when.value).map((s) => (
              <div key={s.key} className="setting">
                <Field s={s} draft={draft} setDraft={setDraft} />
                <Source s={s} onReset={() => reset(s)} />
              </div>
            ))}
            <div className="row-actions"><button className="primary">Save {group.toLowerCase()}</button></div>
          </form>
        ) : (
          <details key={group} className="panel system-settings">
            <summary>
              <span className="ruled-main-col"><h2>{group}</h2><span className="check-detail">Set in .env, needs a restart</span></span>
              <Badge tone="brass">.env</Badge>
            </summary>
            <dl className="readonly-settings">
              {fields.map((s) => (
                <div key={s.key}>
                  <dt>{s.label} <code>{envName(s.key)}</code></dt>
                  <dd>{shown(s.value)}</dd>
                </div>
              ))}
            </dl>
          </details>
        ),
      )}
      {tab.path === "email" && <SystemTestEmail settings={items} />}
      {tab.path === "storage" && <SystemStorage settings={items} />}
    </>
  );
}

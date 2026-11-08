import { useState, type FormEvent } from "react";
import { api, download, json, type Site } from "../api";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";

/** An empty box means "keep forever" (null); anything else is a whole number of days. */
const days = (d: FormData, name: string) => (d.get(name) ? Number(d.get(name)) : null);

function Retention({ site, onChange }: { site: Site; onChange: (s: Site) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    await toast.attempt(
      api<Site>(`/sites/${site.id}`, json("PATCH", {
        retention_delete_days: days(d, "delete_days"),
        retention_strip_email_days: days(d, "strip_days"),
      })).then(onChange),
      "Retention saved",
    );
    setBusy(false);
  }

  return (
    <form className="panel" onSubmit={save} key={`${site.retention_delete_days}-${site.retention_strip_email_days}`}>
      <h2>Data retention</h2>
      <p className="muted">
        The worker applies these every hour, counting from the day each message arrived. Leave a box empty to keep that data.
        Notification copies of the same messages are cleared on the shorter schedule.
      </p>
      <label>Delete feedback after (days)
        <input name="delete_days" type="number" min={1} max={36500} defaultValue={site.retention_delete_days ?? ""} />
        <small> Messages are permanently deleted with their replies and notes.</small>
      </label>
      <label>Remove emails after (days)
        <input name="strip_days" type="number" min={1} max={36500} defaultValue={site.retention_strip_email_days ?? ""} />
        <small> The email address is removed and the message is kept until the feedback is deleted. Must not exceed the delete period.</small>
      </label>
      <button className="primary" disabled={busy}>Save retention</button>
    </form>
  );
}

function Person({ site }: { site: Site }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [found, setFound] = useState<{ email: string; items: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const path = (op: string) => `/sites/${site.id}/privacy/${op}`;
  const body = (address: string) => json("POST", { email: address });

  async function run(work: () => Promise<unknown>, success?: string) {
    setBusy(true);
    const ok = await toast.attempt(work(), success);
    setBusy(false);
    return ok;
  }

  const lookup = (e: FormEvent) => {
    e.preventDefault();
    const address = email.trim();
    return run(async () => setFound({ email: address, items: (await api<{ items: number }>(path("lookup"), body(address))).items }));
  };

  async function erase(address: string) {
    if (!(await confirm({
      title: "Erase this person's data?",
      message: `All messages from ${address} on ${site.name} will be deleted with their replies and notes. This cannot be undone.`,
      confirmLabel: "Erase",
      danger: true,
    }))) return;
    const ok = await run(async () => {
      const { deleted } = await api<{ deleted: number }>(path("erase"), body(address));
      toast.success(`Deleted ${deleted} ${deleted === 1 ? "item" : "items"}`);
    });
    if (ok) setFound({ email: address, items: 0 });
  }

  return (
    <section className="panel" aria-labelledby="person-h">
      <h2 id="person-h">Export or erase personal data</h2>
      <p className="muted">Find everything this site holds for an email address, then export or erase it.</p>
      <form onSubmit={lookup}>
        <label>Email address
          <input type="email" required value={email} onChange={(e) => { setEmail(e.target.value); setFound(null); }} autoComplete="off" />
        </label>
        <button disabled={busy || !email.trim()}>Look up</button>
      </form>
      {found && (
        <div role="status" aria-busy={busy}>
          <p>{found.items === 0 ? "Nothing held for this address." : `${found.items} ${found.items === 1 ? "item" : "items"} found.`}</p>
          {found.items > 0 && (
            <div className="row-actions">
              <button disabled={busy} onClick={() => run(() => download(path("export"), "person-export.zip", body(found.email)))}>
                Export
              </button>
              <button className="danger" disabled={busy} onClick={() => erase(found.email)}>Erase</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default function Privacy(props: { site: Site; onChange: (s: Site) => void }) {
  return (
    <>
      <Retention {...props} />
      <Person site={props.site} />
    </>
  );
}

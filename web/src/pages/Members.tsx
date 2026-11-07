import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, displayName, json, type Member, type Role, type Site } from "../api";
import { Avatar, UserPicker } from "../components";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";
import { Icon } from "../icons";
import { EmptyState } from "../ui/EmptyState";
import { Sheet } from "../ui/Sheet";

const ROLES: Role[] = ["viewer", "editor", "admin"];
const ROLE_HELP: Record<Role, string> = {
  viewer: "Can read feedback",
  editor: "Can also change status",
  admin: "Can also delete feedback and manage the site",
};

export default function Members({ site }: { site: Site }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [adding, setAdding] = useState(false);

  const load = useCallback(
    () => api<Member[]>(`/sites/${site.id}/members`).then(setMembers).catch((e) => setError(e.message)),
    [site.id],
  );
  useEffect(() => void load(), [load]);

  async function upsert(memberEmail: string, memberRole: string) {
    const ok = await toast.attempt(api(`/sites/${site.id}/members`, json("PUT", { email: memberEmail, role: memberRole })), "Member saved");
    load();
    return ok;
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    if (email && (await upsert(email, role))) { setEmail(""); setAdding(false); }
  }

  async function remove(m: Member) {
    if (!(await confirm({ title: `Remove ${displayName(m)}?`, message: `They will lose access to ${site.name}.`, confirmLabel: "Remove", danger: true }))) return;
    await toast.attempt(api(`/sites/${site.id}/members/${m.user_id}`, { method: "DELETE" }), "Member removed");
    load();
  }

  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="section-head">
        <h2>Members <span className="count">{members.length}</span></h2>
        <button className="primary" onClick={() => setAdding(true)}><Icon name="plus" size={18} />Add member</button>
      </div>
      <Sheet open={adding} title="Add member" onClose={() => setAdding(false)}>
        <form onSubmit={add}>
          <div className="field"><span className="field-label">User</span><UserPicker siteId={site.id} value={email} onSelect={setEmail} /></div>
          <label>Role
            <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
          <p className="hint muted">{ROLE_HELP[role]}. Pick an existing user from the list.</p>
          <button className="primary block" disabled={!email}>Add member</button>
          <button type="button" className="plain block" onClick={() => setAdding(false)}>Cancel</button>
        </form>
      </Sheet>
      <ul className="ruled members">
        {members.map((m) => (
          <li key={m.user_id} className="ruled-row member-row">
            <Avatar user={m} />
            <span className="ruled-main-col">
              <strong>{displayName(m)}</strong>
              {displayName(m) !== m.email && <span className="person">{m.email}</span>}
            </span>
            <select value={m.role} onChange={(e) => upsert(m.email, e.target.value)} aria-label={`Role for ${m.email}`}>
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
            <button className="danger" onClick={() => remove(m)}>Remove</button>
          </li>
        ))}
      </ul>
      {members.length === 0 && <EmptyState>No members yet. Superadmins always have access.</EmptyState>}
    </>
  );
}

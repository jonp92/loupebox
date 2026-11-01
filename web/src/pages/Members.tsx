import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, displayName, json, type Member, type Role, type Site } from "../api";
import { Avatar, UserPicker } from "../components";

const ROLES: Role[] = ["viewer", "editor", "admin"];
const ROLE_HELP: Record<Role, string> = {
  viewer: "Can read feedback",
  editor: "Can also change status",
  admin: "Can also delete feedback and manage the site",
};

export default function Members({ site }: { site: Site }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");

  const load = useCallback(
    () => api<Member[]>(`/sites/${site.id}/members`).then(setMembers).catch((e) => setError(e.message)),
    [site.id],
  );
  useEffect(() => void load(), [load]);

  async function upsert(memberEmail: string, memberRole: string) {
    try {
      await api(`/sites/${site.id}/members`, json("PUT", { email: memberEmail, role: memberRole }));
      setError("");
      load();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    if (email && (await upsert(email, role))) setEmail("");
  }

  async function remove(m: Member) {
    if (!confirm(`Remove ${displayName(m)} from ${site.name}?`)) return;
    await api(`/sites/${site.id}/members/${m.user_id}`, { method: "DELETE" }).catch((e) => setError(e.message));
    load();
  }

  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      <section className="card">
        <h2>Add member</h2>
        <form className="add-member" onSubmit={add}>
          <UserPicker siteId={site.id} value={email} onSelect={setEmail} />
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="Role">
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
          <button className="primary" disabled={!email}>Add</button>
        </form>
        <p className="muted hint">{ROLE_HELP[role]}. Pick an existing user from the list.</p>
      </section>
      <h2 className="section">Members <span className="count">{members.length}</span></h2>
      <ul className="list">
        {members.map((m) => (
          <li key={m.user_id}>
            <Avatar user={m} />
            <span className="grow stack">
              <strong>{displayName(m)}</strong>
              {displayName(m) !== m.email && <span className="muted">{m.email}</span>}
            </span>
            <select value={m.role} onChange={(e) => upsert(m.email, e.target.value)} aria-label={`Role for ${m.email}`}>
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
            <button className="danger" onClick={() => remove(m)}>Remove</button>
          </li>
        ))}
        {members.length === 0 && <li className="muted">No members yet. Superadmins always have access.</li>}
      </ul>
    </>
  );
}

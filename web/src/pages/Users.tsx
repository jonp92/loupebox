import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { usePolicy } from "../passwordPolicy";
import { Navigate } from "react-router-dom";
import { api, displayName, json, type User } from "../api";
import { useAuth } from "../auth";
import { toAvatarBlob } from "../avatar";
import { Avatar } from "../components";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";
import { useContextMenu, type MenuItem } from "../triage";
import { Badge } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";
import { Sheet } from "../ui/Sheet";
import { Status } from "../ui/Status";
import { Icon } from "../icons";

const PAGE = 50;

export default function Users() {
  const min = usePolicy().passwordMinLength;
  const confirm = useConfirm();
  const toast = useToast();
  const ctx = useContextMenu();
  const { me, setMe } = useAuth();
  const [page, setPage] = useState<{ items: User[]; total: number }>({ items: [], total: 0 });
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (q.trim()) params.set("q", q.trim());
    return api<{ items: User[]; total: number }>(`/users?${params}`).then(setPage).catch((e) => setError(e.message));
  }, [q, offset]);
  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0); // wait for a pause in typing
    return () => clearTimeout(t);
  }, [load, q]);

  if (!me?.is_superadmin) return <Navigate to="/" replace />;

  const syncMe = (updated: User) => { if (updated.id === me!.id) setMe({ ...me!, ...updated }); };

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const ok = await toast.attempt(api("/users", json("POST", {
      first_name: d.get("first_name"),
      last_name: d.get("last_name"),
      email: d.get("email"),
      password: d.get("password"),
      is_superadmin: d.get("is_superadmin") === "on",
    })), "User created");
    if (!ok) return;
    setCreating(false);
    load();
  }

  async function saveEdit(e: FormEvent<HTMLFormElement>, u: User) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const ok = await toast.attempt(
      api<User>(`/users/${u.id}`, json("PATCH", {
        first_name: d.get("first_name"),
        last_name: d.get("last_name"),
        email: d.get("email"),
      })).then(syncMe),
      "User saved",
    );
    if (!ok) return;
    setEditing(null);
    load();
  }

  async function saveAvatar(u: User, file: File | null) {
    await toast.attempt(
      (file
        ? toAvatarBlob(file).then((image) =>
            api<User>(`/users/${u.id}/avatar`, { method: "PUT", body: image, headers: { "Content-Type": image.type } }))
        : api<User>(`/users/${u.id}/avatar`, { method: "DELETE" })
      ).then(syncMe),
      file ? "Avatar updated" : "Avatar removed",
    );
    load();
    if (fileInput.current) fileInput.current.value = "";
  }

  async function toggle(u: User) {
    await toast.attempt(api(`/users/${u.id}`, json("PATCH", { is_active: !u.is_active })), u.is_active ? "User deactivated" : "User activated");
    load();
  }

  async function toggleSuperadmin(u: User) {
    const next = !u.is_superadmin;
    const name = displayName(u);
    const ok = await confirm(
      next
        ? { title: `Make ${name} a superadmin?`, message: "They will have full access to every site and user.", confirmLabel: "Make superadmin" }
        : { title: `Remove superadmin from ${name}?`, confirmLabel: "Remove", danger: true },
    );
    if (!ok) return;
    await toast.attempt(api(`/users/${u.id}`, json("PATCH", { is_superadmin: next })), next ? "Superadmin granted" : "Superadmin removed");
    load();
  }

  async function resetTotp(u: User) {
    const ok = await confirm({
      title: `Turn off two-factor for ${displayName(u)}?`,
      message: "Use this when they are locked out. They will be signed out everywhere and can set it up again.",
      confirmLabel: "Turn off",
      danger: true,
    });
    if (!ok) return;
    await toast.attempt(api(`/users/${u.id}/totp`, { method: "DELETE" }), "Two-factor turned off");
    load();
  }

  const menuFor = (u: User): MenuItem[] => [
    ...(u.totp_enabled ? [{ label: "Reset 2FA", onSelect: () => resetTotp(u), danger: true }] : []),
    { label: u.is_superadmin ? "Remove superadmin" : "Make superadmin", onSelect: () => toggleSuperadmin(u) },
    { label: u.is_active ? "Disable" : "Enable", onSelect: () => toggle(u), danger: u.is_active },
  ];

  const editUser = page.items.find((u) => u.id === editing);
  const search = (value: string) => { setQ(value); setOffset(0); };

  return (
    <>
      <div className="page-head">
        <h1>Users</h1>
        <span className="count">{page.total}</span>
        <button className="primary grow-end" onClick={() => setCreating(true)}><Icon name="plus" size={18} />New user</button>
      </div>
      <Sheet open={creating} title="New user" onClose={() => setCreating(false)}>
        <form onSubmit={create}>
          <div className="grid-2">
            <label>First name<input name="first_name" required maxLength={100} /></label>
            <label>Last name<input name="last_name" required maxLength={100} /></label>
          </div>
          <label>Email<input name="email" type="email" required /></label>
          <label>Password<input name="password" type="password" minLength={min} required autoComplete="new-password" aria-describedby="password-hint" /></label>
          <p id="password-hint" className="hint muted">At least {min} characters.</p>
          <label className="inline"><input name="is_superadmin" type="checkbox" /> Superadmin</label>
          <button className="primary block">Create user</button>
          <button type="button" className="plain block" onClick={() => setCreating(false)}>Cancel</button>
        </form>
      </Sheet>
      <Sheet open={editing !== null && editUser !== undefined} title="Edit user" onClose={() => setEditing(null)}>
        {editUser && (
          <form onSubmit={(e) => saveEdit(e, editUser)}>
            <div className="grid-2">
              <label>First name<input name="first_name" defaultValue={editUser.first_name} required maxLength={100} /></label>
              <label>Last name<input name="last_name" defaultValue={editUser.last_name} required maxLength={100} /></label>
            </div>
            <label>Email<input name="email" type="email" defaultValue={editUser.email} required /></label>
            <div className="avatar-row">
              <Avatar user={editUser} size="lg" />
              <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => saveAvatar(editUser, e.target.files?.[0] ?? null)} />
              <button type="button" onClick={() => fileInput.current?.click()}>Upload avatar</button>
              {editUser.avatar_url && <button type="button" className="danger" onClick={() => saveAvatar(editUser, null)}>Remove avatar</button>}
            </div>
            <button className="primary block">Save</button>
            <button type="button" className="plain block" onClick={() => setEditing(null)}>Cancel</button>
          </form>
        )}
      </Sheet>
      <div className="toolbar">
        <input type="search" value={q} onChange={(e) => search(e.target.value)} placeholder="Search by name or email…" aria-label="Search users" maxLength={100} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {page.items.length === 0 && !error ? (
        <EmptyState>{q.trim() ? `No users match “${q.trim()}”.` : "No users yet."}</EmptyState>
      ) : (
        <table className="users-table">
          <caption className="sr-only">Users{q.trim() ? ` matching “${q.trim()}”` : ""}</caption>
          <thead>
            <tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th><th scope="col">2FA</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {page.items.map((u) => (
                <tr key={u.id} className={u.is_active ? undefined : "inactive"}>
                  <th scope="row">
                    <span className="user-name">
                      <Avatar user={u} />
                      <span>{displayName(u)}{u.id === me.id && <span className="muted"> (you)</span>}</span>
                    </span>
                  </th>
                  <td className="user-email">{u.email}</td>
                  {/* Only what stands out is drawn: the common case (a plain, active user) is spoken, not shown.
                      On a phone the badge has no "Role" label and sits after 2FA on the same line. */}
                  <td data-label="Role" className={u.is_superadmin ? undefined : "quiet"}>
                    {u.is_superadmin ? <Badge tone="brass">Superadmin</Badge> : "User"}
                  </td>
                  <td data-label="2FA"><Status tone={u.totp_enabled ? "ok" : "muted"}>{u.totp_enabled ? "On" : "Off"}</Status></td>
                  <td data-label="Status" className={u.is_active ? "quiet" : undefined}>
                    {u.is_active ? "Active" : <Status tone="danger">Disabled</Status>}
                  </td>
                  <td className="user-actions">
                    <button onClick={() => setEditing(u.id)} aria-label={`Edit ${displayName(u)}`}>Edit</button>
                    {u.id !== me.id && (
                      <button className="menu-btn" aria-label={`More actions for ${displayName(u)}`} aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, menuFor(u))}><Icon name="more" /></button>
                    )}
                  </td>
                </tr>
            ))}
          </tbody>
        </table>
      )}
      {ctx.node}
      {page.total > PAGE && (
        <div className="toolbar">
          <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Previous</button>
          <span className="muted">{offset + 1}–{Math.min(offset + PAGE, page.total)} of {page.total}</span>
          <button disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
        </div>
      )}
    </>
  );
}

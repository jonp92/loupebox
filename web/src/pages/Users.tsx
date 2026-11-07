import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
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
import { Status } from "../ui/Status";

const PAGE = 50;

export default function Users() {
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

  const search = (value: string) => { setQ(value); setOffset(0); };

  return (
    <>
      <div className="page-head">
        <h1>Users</h1>
        <span className="count">{page.total}</span>
        <button className="primary grow-end" onClick={() => setCreating(!creating)} aria-expanded={creating}>
          {creating ? "Cancel" : "New user"}
        </button>
      </div>
      {creating && (
        <form className="card" onSubmit={create}>
          <h2>New user</h2>
          <div className="grid-2">
            <label>First name<input name="first_name" required maxLength={100} autoFocus /></label>
            <label>Last name<input name="last_name" required maxLength={100} /></label>
          </div>
          <label>Email<input name="email" type="email" required /></label>
          <label>Password <small>(12+ characters)</small><input name="password" type="password" minLength={12} required autoComplete="new-password" /></label>
          <label className="inline"><input name="is_superadmin" type="checkbox" /> Superadmin</label>
          <button className="primary">Create user</button>
        </form>
      )}
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
            {page.items.map((u) =>
              editing === u.id ? (
                <tr key={u.id} className="editing">
                  <td colSpan={6}>
                    <form className="edit-user" onSubmit={(e) => saveEdit(e, u)}>
                      <label>First name<input name="first_name" defaultValue={u.first_name} required maxLength={100} autoFocus /></label>
                      <label>Last name<input name="last_name" defaultValue={u.last_name} required maxLength={100} /></label>
                      <label className="wide">Email<input name="email" type="email" defaultValue={u.email} required /></label>
                      <div className="wide avatar-row">
                        <Avatar user={u} size="lg" />
                        <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => saveAvatar(u, e.target.files?.[0] ?? null)} />
                        <button type="button" onClick={() => fileInput.current?.click()}>Upload avatar</button>
                        {u.avatar_url && <button type="button" className="danger" onClick={() => saveAvatar(u, null)}>Remove avatar</button>}
                      </div>
                      <div className="row-actions">
                        <button type="button" onClick={() => setEditing(null)}>Cancel</button>
                        <button className="primary">Save</button>
                      </div>
                    </form>
                  </td>
                </tr>
              ) : (
                <tr key={u.id} className={u.is_active ? undefined : "inactive"}>
                  <th scope="row">
                    <span className="user-name">
                      <Avatar user={u} />
                      <span>{displayName(u)}{u.id === me.id && <span className="muted"> (you)</span>}</span>
                    </span>
                  </th>
                  <td className="user-email">{u.email}</td>
                  <td data-label="Role"><Badge tone={u.is_superadmin ? "brass" : "muted"}>{u.is_superadmin ? "Superadmin" : "User"}</Badge></td>
                  <td data-label="2FA"><Status tone={u.totp_enabled ? "ok" : "danger"}>{u.totp_enabled ? "On" : "Off"}</Status></td>
                  <td data-label="Status"><Status tone={u.is_active ? "ok" : "danger"}>{u.is_active ? "Active" : "Disabled"}</Status></td>
                  <td className="user-actions">
                    <button onClick={() => setEditing(u.id)} aria-label={`Edit ${displayName(u)}`}>Edit</button>
                    {u.id !== me.id && (
                      <button className="menu-btn" aria-label={`More actions for ${displayName(u)}`} aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, menuFor(u))}>⋯</button>
                    )}
                  </td>
                </tr>
              ),
            )}
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

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, displayName, json, type User } from "../api";
import { useAuth } from "../auth";
import { toAvatarBlob } from "../avatar";
import { Avatar } from "../components";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";

export default function Users() {
  const confirm = useConfirm();
  const toast = useToast();
  const { me, setMe } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const load = () => api<User[]>("/users").then(setUsers).catch((e) => setError(e.message));
  useEffect(() => void load(), []);

  if (!me?.is_superadmin) return <Navigate to="/" replace />;

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const d = new FormData(form);
    const ok = await toast.attempt(api("/users", json("POST", {
      first_name: d.get("first_name"),
      last_name: d.get("last_name"),
      email: d.get("email"),
      password: d.get("password"),
      is_superadmin: d.get("is_superadmin") === "on",
    })), "User created");
    if (!ok) return;
    form.reset();
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
      })).then((updated) => { if (updated.id === me!.id) setMe({ ...me!, ...updated }); }),
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
      ).then((updated) => { if (updated.id === me!.id) setMe({ ...me!, ...updated }); }),
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

  return (
    <>
      <div className="page-head"><h1>Users</h1><span className="count">{users.length}</span></div>
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="list users">
        {users.map((u) =>
          editing === u.id ? (
            <li key={u.id} className="editing">
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
            </li>
          ) : (
            <li key={u.id}>
              <Avatar user={u} />
              <span className="grow stack">
                <strong>{displayName(u)}</strong>
                {displayName(u) !== u.email && <span className="muted">{u.email}</span>}
                {(u.is_superadmin || !u.is_active || u.totp_enabled) && (
                  <span className="origins">
                    {u.is_superadmin && <span className="badge">superadmin</span>}
                    {u.totp_enabled && <span className="badge read">2FA</span>}
                    {!u.is_active && <span className="badge warn">disabled</span>}
                  </span>
                )}
              </span>
              <button onClick={() => setEditing(u.id)}>Edit</button>
              {u.totp_enabled && u.id !== me.id && <button onClick={() => resetTotp(u)}>Reset 2FA</button>}
              {u.id !== me.id && (
                <button onClick={() => toggleSuperadmin(u)}>{u.is_superadmin ? "Remove superadmin" : "Make superadmin"}</button>
              )}
              {u.id !== me.id && <button onClick={() => toggle(u)}>{u.is_active ? "Disable" : "Enable"}</button>}
            </li>
          ),
        )}
      </ul>
      <form className="card" onSubmit={create}>
        <h2>New user</h2>
        <div className="grid-2">
          <label>First name<input name="first_name" required maxLength={100} /></label>
          <label>Last name<input name="last_name" required maxLength={100} /></label>
        </div>
        <label>Email<input name="email" type="email" required /></label>
        <label>Password <small>(12+ characters)</small><input name="password" type="password" minLength={12} required autoComplete="new-password" /></label>
        <label className="inline"><input name="is_superadmin" type="checkbox" /> Superadmin</label>
        <button className="primary">Create user</button>
      </form>
    </>
  );
}

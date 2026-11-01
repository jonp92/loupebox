import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, displayName, json, type User } from "../api";
import { useAuth } from "../auth";
import { Avatar } from "../components";

export default function Users() {
  const { me, setMe } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const load = () => api<User[]>("/users").then(setUsers).catch((e) => setError(e.message));
  useEffect(() => void load(), []);

  if (!me?.is_superadmin) return <Navigate to="/" replace />;

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const d = new FormData(form);
    try {
      await api("/users", json("POST", {
        first_name: d.get("first_name"),
        last_name: d.get("last_name"),
        email: d.get("email"),
        password: d.get("password"),
        is_superadmin: d.get("is_superadmin") === "on",
      }));
      form.reset();
      setError("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function saveEdit(e: FormEvent<HTMLFormElement>, u: User) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    try {
      const updated = await api<User>(`/users/${u.id}`, json("PATCH", {
        first_name: d.get("first_name"),
        last_name: d.get("last_name"),
        email: d.get("email"),
      }));
      if (updated.id === me!.id) setMe({ ...me!, ...updated });
      setEditing(null);
      setError("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function toggle(u: User) {
    await api(`/users/${u.id}`, json("PATCH", { is_active: !u.is_active })).catch((e) => setError(e.message));
    load();
  }

  return (
    <>
      <div className="page-head"><h1>Users</h1><span className="count">{users.length}</span></div>
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="list">
        {users.map((u) =>
          editing === u.id ? (
            <li key={u.id} className="editing">
              <form className="edit-user" onSubmit={(e) => saveEdit(e, u)}>
                <label>First name<input name="first_name" defaultValue={u.first_name} required maxLength={100} autoFocus /></label>
                <label>Last name<input name="last_name" defaultValue={u.last_name} required maxLength={100} /></label>
                <label className="wide">Email<input name="email" type="email" defaultValue={u.email} required /></label>
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
              </span>
              {u.is_superadmin && <span className="badge">superadmin</span>}
              {!u.is_active && <span className="badge warn">disabled</span>}
              <button onClick={() => setEditing(u.id)}>Edit</button>
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

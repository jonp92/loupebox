import { useRef, useState, type FormEvent } from "react";
import { api, changePassword, displayName, type Me } from "../api";
import { useAuth } from "../auth";
import { AVATAR_SIZE, toAvatarBlob } from "../avatar";
import { Avatar } from "../components";
import TwoFactor from "../TwoFactor";

export default function Profile() {
  const { me, setMe } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const [avatarMsg, setAvatarMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!me) return null;

  async function saveAvatar(image: Blob | null) {
    setBusy(true);
    try {
      const updated = image
        ? await api<Me>("/auth/me/avatar", { method: "PUT", body: image, headers: { "Content-Type": image.type } })
        : await api<Me>("/auth/me/avatar", { method: "DELETE" });
      setMe(updated);
      setAvatarMsg({ ok: true, text: image ? "Avatar updated" : "Avatar removed" });
    } catch (e) {
      setAvatarMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    try {
      await saveAvatar(await toAvatarBlob(file));
    } catch (e) {
      setAvatarMsg({ ok: false, text: (e as Error).message });
    }
    if (fileInput.current) fileInput.current.value = "";
  }

  async function submitPassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const d = new FormData(form);
    if (d.get("new") !== d.get("confirm")) return setPwMsg({ ok: false, text: "New passwords don't match" });
    setBusy(true);
    try {
      await changePassword(String(d.get("current")), String(d.get("new")));
      form.reset();
      setPwMsg({ ok: true, text: "Password changed. Other devices have been signed out." });
    } catch (err) {
      setPwMsg({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head"><h1>Your profile</h1></div>

      <section className="card profile-head">
        <Avatar user={me} size="xl" />
        <div>
          <h2>{displayName(me)}</h2>
          <p className="muted">{me.email}</p>
          <p className="muted hint">
            {me.is_superadmin ? "Superadmin. " : ""}Name and email are managed by a superadmin.
          </p>
        </div>
      </section>

      <section className="card">
        <h2>Avatar</h2>
        <div className="avatar-row">
          <Avatar user={me} size="lg" />
          <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => onFile(e.target.files?.[0])} />
          <button className="primary" disabled={busy} onClick={() => fileInput.current?.click()}>Upload image</button>
          {me.avatar_url && <button className="danger" disabled={busy} onClick={() => saveAvatar(null)}>Remove</button>}
        </div>
        <p className="muted hint">Images are cropped to a square and resized to {AVATAR_SIZE}×{AVATAR_SIZE}.</p>
        {avatarMsg && <p className={avatarMsg.ok ? "success" : "error"} role="status">{avatarMsg.text}</p>}
      </section>

      <form className="card" onSubmit={submitPassword}>
        <h2>Change password</h2>
        <label>Current password<input name="current" type="password" autoComplete="current-password" required /></label>
        <label>New password <small>(12+ characters)</small><input name="new" type="password" autoComplete="new-password" minLength={12} required /></label>
        <label>Confirm new password<input name="confirm" type="password" autoComplete="new-password" minLength={12} required /></label>
        {pwMsg && <p className={pwMsg.ok ? "success" : "error"} role="status">{pwMsg.text}</p>}
        <button className="primary" disabled={busy}>Change password</button>
      </form>

      <TwoFactor />
    </>
  );
}

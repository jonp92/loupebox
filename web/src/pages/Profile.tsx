import { useRef, useState, type FormEvent } from "react";
import { api, changePassword, displayName, type Me } from "../api";
import { useAuth } from "../auth";
import { Avatar } from "../components";

const SIZE = 256;
const MAX_INPUT_BYTES = 10 * 1024 * 1024;

/** Center-crop to a square and downscale so the upload stays small. */
async function toAvatarBlob(file: File): Promise<Blob> {
  if (!/^image\/(png|jpeg|webp|gif|bmp)$/.test(file.type)) throw new Error("Choose a PNG, JPEG or WebP image");
  if (file.size > MAX_INPUT_BYTES) throw new Error("Image is too large (10 MB max)");
  const bitmap = await createImageBitmap(file).catch(() => {
    throw new Error("Could not read that image");
  });
  const side = Math.min(bitmap.width, bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, SIZE, SIZE);
  ctx.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, SIZE, SIZE);
  bitmap.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Could not process that image"))), "image/jpeg", 0.85),
  );
}

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
        <p className="muted hint">Images are cropped to a square and resized to {SIZE}×{SIZE}.</p>
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
    </>
  );
}

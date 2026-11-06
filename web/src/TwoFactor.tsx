import { useMemo, useState, type FormEvent } from "react";
import qrcode from "qrcode-generator";
import { api, json, totpChange, type Me } from "./api";
import { useAuth } from "./auth";
import { useToast } from "./toast";

interface Setup { secret: string; uri: string }

/** Drawn as SVG rects, so the strict CSP (no data: images, no inline styles) isn't a problem. */
function QrCode({ text }: { text: string }) {
  const { size, path } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount();
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c} ${r}h1v1h-1z`;
    return { size: n, path: d };
  }, [text]);
  const quiet = 3;
  return (
    <svg className="qr" viewBox={`${-quiet} ${-quiet} ${size + quiet * 2} ${size + quiet * 2}`} role="img" aria-label="QR code for your authenticator app" shapeRendering="crispEdges">
      <rect x={-quiet} y={-quiet} width={size + quiet * 2} height={size + quiet * 2} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  );
}

function RecoveryList({ codes }: { codes: string[] }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="recovery">
      <p><strong>Save these recovery codes.</strong> Each works once if you lose your authenticator. They won't be shown again.</p>
      <ul className="codes">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ul>
      <button
        type="button"
        onClick={() => navigator.clipboard.writeText(codes.join("\n")).then(() => setCopied(true), () => setCopied(false))}
      >
        {copied ? "Copied" : "Copy codes"}
      </button>
    </div>
  );
}

export default function TwoFactor() {
  const { me, setMe } = useAuth();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<"disable" | "regenerate" | null>(null);
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!me) return null;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const refreshMe = () => api<Me>("/auth/me").then(setMe);

  const start = () => run(async () => setSetup(await api<Setup>("/auth/me/totp/setup", { method: "POST" })));

  function confirm(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const body = { password: d.get("password"), code: d.get("code") };
    void run(async () => {
      const r = await totpChange<{ access_token: string; recovery_codes: string[] }>("/auth/me/totp/enable", body);
      setCodes(r.recovery_codes);
      setSetup(null);
      await refreshMe();
    });
  }

  function proof(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const d = new FormData(form);
    const body = { password: d.get("password"), code: d.get("code") };
    void run(async () => {
      if (mode === "disable") {
        await totpChange("/auth/me/totp/disable", body);
        setCodes(null);
        toast.success("Two-factor authentication is off. Other devices have been signed out.");
      } else {
        setCodes((await api<{ recovery_codes: string[] }>("/auth/me/totp/recovery-codes", json("POST", body))).recovery_codes);
      }
      setMode(null);
      await refreshMe();
    });
  }

  return (
    <section className="card">
      <h2>Two-factor authentication</h2>
      {!me.totp_enabled && !setup && (
        <>
          <p className="muted">Ask for a code from an authenticator app (1Password, Authy, Google Authenticator…) when you sign in.</p>
          <button className="primary" disabled={busy} onClick={start}>Set up</button>
        </>
      )}

      {setup && (
        <form onSubmit={confirm} className="totp-setup">
          <p>Scan this with your authenticator app, then enter the 6-digit code it shows.</p>
          <QrCode text={setup.uri} />
          <p className="muted hint">Can't scan? Enter this key instead: <code>{setup.secret}</code></p>
          <label>Code<input name="code" inputMode="numeric" pattern="[0-9 ]*" maxLength={7} autoComplete="one-time-code" required autoFocus /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
          <div className="row-actions">
            <button type="button" onClick={() => setSetup(null)}>Cancel</button>
            <button className="primary" disabled={busy}>Turn on</button>
          </div>
        </form>
      )}

      {me.totp_enabled && (
        <>
          <p className="success">On. {me.recovery_codes_left} recovery code{me.recovery_codes_left === 1 ? "" : "s"} left.</p>
          {codes && <RecoveryList codes={codes} />}
          {mode ? (
            <form onSubmit={proof} className="totp-proof">
              <p className="muted">{mode === "disable" ? "Confirm to turn off two-factor authentication." : "Confirm to replace your recovery codes. The old ones stop working."}</p>
              <label>Password<input name="password" type="password" autoComplete="current-password" required autoFocus /></label>
              <label>Authenticator or recovery code<input name="code" autoComplete="one-time-code" maxLength={16} required /></label>
              <div className="row-actions">
                <button type="button" onClick={() => setMode(null)}>Cancel</button>
                <button className={mode === "disable" ? "danger" : "primary"} disabled={busy}>
                  {mode === "disable" ? "Turn off" : "New codes"}
                </button>
              </div>
            </form>
          ) : (
            <div className="avatar-row">
              <button disabled={busy} onClick={() => setMode("regenerate")}>New recovery codes</button>
              <button className="danger" disabled={busy} onClick={() => { setMode("disable"); setCodes(null); }}>Turn off</button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

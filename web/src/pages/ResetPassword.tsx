import { autoFocusField } from "../focus";
import { usePolicy } from "../passwordPolicy";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { ThemeToggle } from "../shell";
import { api, json } from "../api";
import { Logo } from "../components";

/** Request a reset link by email. The answer is the same whether or not the address has an account. */
export function ForgotPassword() {
  const [done, setDone] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const email = String(new FormData(e.currentTarget).get("email"));
    setBusy(true);
    setError("");
    try {
      const r = await api<{ status: string }>("/auth/password-reset/request", json("POST", { email }));
      setDone(r.status);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-theme"><ThemeToggle /></div>
      <form className="login-card" onSubmit={submit}>
        <Logo size={56} className="big" />
        <h1>Reset your password</h1>
        {done ? (
          <p className="success" role="status">{done}</p>
        ) : (
          <>
            <p className="muted">Enter your email and we'll send you a link to choose a new password.</p>
            <label>Email<input name="email" type="email" autoComplete="username" required autoFocus={autoFocusField} /></label>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="primary block" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
          </>
        )}
        <p className="login-links"><Link to="/login">Back to sign in</Link></p>
      </form>
    </div>
  );
}

/** Choose a new password. The token comes from the link's #fragment and is removed from the address bar. */
export function ResetPassword() {
  const { hash } = useLocation();
  const [token, setToken] = useState<string | null>(null);
  const [done, setDone] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const min = usePolicy().passwordMinLength;

  useEffect(() => {
    const found = new URLSearchParams(hash.slice(1)).get("token");
    if (found) {
      setToken(found);
      history.replaceState(null, "", location.pathname); // keep it out of history and screenshots
    }
  }, [hash]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    if (d.get("new") !== d.get("confirm")) return setError("Passwords don't match");
    setBusy(true);
    setError("");
    try {
      const r = await api<{ status: string }>(
        "/auth/password-reset/confirm", json("POST", { token, new_password: String(d.get("new")) }),
      );
      setDone(r.status);
      setToken(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-theme"><ThemeToggle /></div>
      <form className="login-card" onSubmit={submit}>
        <Logo size={56} className="big" />
        <h1>Choose a new password</h1>
        {done ? (
          <>
            <p className="success" role="status">{done}</p>
            <p className="login-links"><Link to="/login">Sign in</Link></p>
          </>
        ) : token ? (
          <>
            <p className="muted">You'll be signed out everywhere and asked to sign in again.</p>
            <label>New password <small>({min}+ characters)</small><input name="new" type="password" autoComplete="new-password" minLength={min} required autoFocus={autoFocusField} /></label>
            <label>Confirm new password<input name="confirm" type="password" autoComplete="new-password" minLength={min} required /></label>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="primary block" disabled={busy}>{busy ? "Saving…" : "Change password"}</button>
          </>
        ) : (
          <>
            <p className="error" role="alert">{error || "This reset link is missing its code. Request a new one."}</p>
            <p className="login-links"><Link to="/forgot-password">Request a new link</Link></p>
          </>
        )}
      </form>
    </div>
  );
}

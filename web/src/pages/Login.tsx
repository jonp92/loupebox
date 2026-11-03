import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ThemeToggle } from "../App";
import { useAuth } from "../auth";
import { Logo } from "../components";

export default function Login() {
  const { me, loading, signIn, completeMfa } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [recovery, setRecovery] = useState(false);

  if (me) return <Navigate to="/" replace />;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    void run(async () => {
      const token = await signIn(String(form.get("email")), String(form.get("password")));
      if (token === null) navigate("/");
      else setMfaToken(token);
    });
  }

  function submitCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code"));
    void run(async () => {
      await completeMfa(mfaToken!, code);
      navigate("/");
    });
  }

  function back() {
    setMfaToken(null);
    setRecovery(false);
    setError("");
  }

  return (
    <div className="login-page">
      <div className="login-theme"><ThemeToggle /></div>
      {mfaToken === null ? (
        <form className="login-card" onSubmit={submit}>
          <Logo size={56} className="big" />
          <h1>Ganymede</h1>
          <p className="muted">Sign in to review feedback</p>
          <label>Email<input name="email" type="email" autoComplete="username" required autoFocus /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary block" disabled={busy || loading}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      ) : (
        <form className="login-card" onSubmit={submitCode} key={recovery ? "recovery" : "code"}>
          <Logo size={56} className="big" />
          <h1>Two-factor authentication</h1>
          <p className="muted">
            {recovery ? "Enter one of your recovery codes" : "Enter the 6-digit code from your authenticator app"}
          </p>
          <label>
            {recovery ? "Recovery code" : "Code"}
            <input
              name="code"
              required
              autoFocus
              autoComplete="one-time-code"
              {...(recovery
                ? { placeholder: "xxxxx-xxxxx", maxLength: 16 }
                : { inputMode: "numeric", pattern: "[0-9 ]*", placeholder: "123456", maxLength: 7 })}
            />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary block" disabled={busy}>{busy ? "Verifying…" : "Verify"}</button>
          <p className="login-links">
            <button type="button" className="link" onClick={() => { setRecovery(!recovery); setError(""); }}>
              {recovery ? "Use an authenticator code" : "Use a recovery code"}
            </button>
            {" · "}
            <button type="button" className="link" onClick={back}>Back</button>
          </p>
        </form>
      )}
    </div>
  );
}

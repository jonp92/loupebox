import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ThemeToggle } from "../App";
import { useAuth } from "../auth";
import { Logo } from "../components";

export default function Login() {
  const { me, loading, signIn } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to="/" replace />;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await signIn(String(form.get("email")), String(form.get("password")));
      navigate("/");
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
        <h1>Ganymede</h1>
        <p className="muted">Sign in to review feedback</p>
        <label>Email<input name="email" type="email" autoComplete="username" required autoFocus /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary block" disabled={busy || loading}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}

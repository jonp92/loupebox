import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { api, displayName, type Me } from "./api";
import { Avatar, Logo, OfflineBanner } from "./components";
import { useAuth } from "./auth";
import Audit from "./pages/Audit";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import { ForgotPassword, ResetPassword } from "./pages/ResetPassword";
import SiteDetail from "./pages/SiteDetail";
import Dashboard from "./pages/Dashboard";
import Sites from "./pages/Sites";
import Users from "./pages/Users";
import { useTheme } from "./theme";

const THEME_ICON = { system: "◐", light: "☀", dark: "☾" } as const;

export function ThemeToggle() {
  const [theme, cycle] = useTheme();
  return (
    <button className="icon" onClick={cycle} title={`Theme: ${theme} (click to change)`} aria-label={`Theme: ${theme}`}>
      {THEME_ICON[theme]}
    </button>
  );
}

function UserMenu({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="usermenu" ref={box}>
      <button className="avatar-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Avatar user={me} />
        <span className="hide-sm">{me.first_name || me.email}</span>
        <span className="caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="dropdown" role="menu">
          <div className="dropdown-head">
            <strong>{displayName(me)}</strong>
            <span className="muted">{me.email}</span>
          </div>
          <Link to="/profile" role="menuitem">Profile &amp; password</Link>
          <button role="menuitem" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}

function Footer() {
  const [version, setVersion] = useState("");
  useEffect(() => {
    api<{ app_version: string }>("/version").then((v) => setVersion(v.app_version), () => {});
  }, []);
  return <footer className="appfooter muted">Loupebox{version && ` ${version}`}</footer>;
}

function Layout() {
  const { me, loading, signOut } = useAuth();
  if (loading) return <p className="center muted">Loading…</p>;
  if (!me) return <Navigate to="/login" replace />;
  return (
    <>
      <header className="topbar">
        <NavLink to="/" className="brand"><Logo /> Loupebox</NavLink>
        <nav className="mainnav">
          <NavLink to="/" end>Dashboard</NavLink>
          {/* Sites stays highlighted on /sites/:id too (NavLink matches the prefix) */}
          <NavLink to="/sites">Sites</NavLink>
          {me.is_superadmin && <NavLink to="/users">Users</NavLink>}
          {me.is_superadmin && <NavLink to="/audit">Audit</NavLink>}
        </nav>
        <div className="spacer" />
        <ThemeToggle />
        <UserMenu me={me} onSignOut={signOut} />
      </header>
      <main><Outlet /></main>
      <Footer />
    </>
  );
}

export default function App() {
  return (
    <>
      <OfflineBanner />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="sites" element={<Sites />} />
          <Route path="sites/:siteId/*" element={<SiteDetail />} />
          <Route path="users" element={<Users />} />
          <Route path="audit" element={<Audit />} />
          <Route path="profile" element={<Profile />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

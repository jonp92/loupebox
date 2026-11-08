import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { api, displayName, type Me } from "./api";
import { Avatar, Logo } from "./components";
import { hasInbox, useAuth } from "./auth";
import { Icon, type IconName } from "./icons";
import { useTheme } from "./theme";

const THEME_ICON: Record<string, IconName> = { system: "contrast", light: "sun", dark: "moon" };
const WIDE = "(min-width: 1024px)"; // sidebar at this width and up, drawer below (tokens.css can't feed media queries)

export function ThemeToggle() {
  const [theme, cycle] = useTheme();
  return (
    <button className="icon" onClick={cycle} title={`Theme: ${theme} (click to change)`} aria-label={`Theme: ${theme}`}>
      <Icon name={THEME_ICON[theme]} />
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
      <button className="avatar-btn" aria-haspopup="menu" aria-expanded={open} aria-label="Account menu" onClick={() => setOpen(!open)}>
        <Avatar user={me} />
        <span className="hide-sm">{me.first_name || me.email}</span>
        <span className="hide-sm caret"><Icon name="caret" size={16} /></span>
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

function SidebarFooter() {
  const [version, setVersion] = useState("");
  useEffect(() => {
    api<{ app_version: string }>("/version").then((v) => setVersion(v.app_version), () => {});
  }, []);
  return (
    <footer className="sidebar-foot">
      Loupebox{version && ` ${version}`}
      <a href="https://github.com/jonp92/loupebox" target="_blank" rel="noopener noreferrer" aria-label="Source code on GitHub (opens in a new tab)">Source</a>
    </footer>
  );
}

function NavItem({ to, icon, end, children }: { to: string; icon: IconName; end?: boolean; children: string }) {
  // Sites stays highlighted on /sites/:id too (NavLink matches the prefix)
  return <NavLink to={to} end={end} className="nav-item"><Icon name={icon} /><span>{children}</span></NavLink>;
}

function useWide() {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches);
  useEffect(() => {
    const mq = window.matchMedia(WIDE);
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return wide;
}

export function Layout() {
  const { me, loading, signOut } = useAuth();
  const wide = useWide();
  const [drawer, setDrawer] = useState(false);
  const { pathname } = useLocation();
  const menuBtn = useRef<HTMLButtonElement>(null);
  const side = useRef<HTMLElement>(null);
  const open = drawer && !wide;

  useEffect(() => setDrawer(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    side.current?.querySelector<HTMLElement>(".drawer-close")?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    document.addEventListener("keydown", esc);
    const button = menuBtn.current;
    return () => {
      document.removeEventListener("keydown", esc);
      button?.focus(); // back to where the drawer was opened from
    };
  }, [open]);

  if (loading) return <p className="center muted">Loading…</p>;
  if (!me) return <Navigate to="/login" replace />;
  // Required 2FA and none yet: the API refuses everything but setup, so only Profile is offered.
  if (me.totp_required && pathname !== "/profile") return <Navigate to="/profile" replace />;
  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      {/* Off-canvas below 1024px: inert while closed (out of the tab order), and the page behind is inert while open. */}
      <aside id="sidebar" ref={side} className="sidebar" data-open={open} inert={!wide && !open} aria-label="Main">
        <div className="sidebar-head">
          <NavLink to="/" className="brand" aria-label="Loupebox"><Logo wordmark /></NavLink>
          <button className="icon drawer-close" onClick={() => setDrawer(false)} aria-label="Close menu"><Icon name="close" /></button>
        </div>
        {!me.totp_required && <nav className="sidebar-nav" aria-label="Primary">
          <p className="nav-group">Triage</p>
          <NavItem to="/" end icon="dashboard">Dashboard</NavItem>
          {hasInbox(me) && <NavItem to="/inbox" icon="inbox">Inbox</NavItem>}
          <NavItem to="/sites" icon="sites">Sites</NavItem>
          {me.is_superadmin && (
            <>
              <p className="nav-group">Admin</p>
              <NavItem to="/users" icon="users">Users</NavItem>
              <NavItem to="/audit" icon="audit">Audit</NavItem>
              <NavItem to="/system" icon="system">System</NavItem>
            </>
          )}
        </nav>}
        <SidebarFooter />
      </aside>
      {open && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden />}
      <div className="shell-main" inert={open}>
        <header className="appbar">
          {!me.totp_required && <button ref={menuBtn} className="icon menu-btn" onClick={() => setDrawer(true)} aria-label="Open menu" aria-expanded={open} aria-controls="sidebar">
            <Icon name="menu" />
          </button>}
          <NavLink to="/" className="brand brand-bar" aria-label="Loupebox"><Logo wordmark /></NavLink>
          <div className="spacer" />
          <ThemeToggle />
          <UserMenu me={me} onSignOut={signOut} />
        </header>
        <main id="main"><Outlet /></main>
      </div>
    </div>
  );
}

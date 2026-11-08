import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import * as client from "./api";
import type { Me } from "./api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  /** Resolves to an MFA token when a code is still needed, otherwise null (signed in). */
  signIn: (email: string, password: string) => Promise<string | null>;
  completeMfa: (mfaToken: string, code: string) => Promise<void>;
  signOut: () => Promise<void>;
  setMe: (me: Me) => void;
}

const Ctx = createContext<AuthState>(null!);
export const useAuth = () => useContext(Ctx);

/** The one site a regular user belongs to, if that is all they have: there is no list to choose from. */
export const soleSiteId = (me: Me | null) =>
  me && !me.is_superadmin && me.memberships.length === 1 ? me.memberships[0].site_id : null;

/** The inbox only adds something over a site's own list when there is more than one site to look across. */
export const hasInbox = (me: Me | null) => Boolean(me && (me.is_superadmin || me.memberships.length > 1));

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    client.setLogoutHandler(() => setMe(null));
    // Restore the session from the refresh cookie on page load.
    client
      .refresh()
      .then((ok) => (ok ? client.api<Me>("/auth/me").then(setMe) : undefined))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const mfaToken = await client.login(email, password);
    if (mfaToken === null) setMe(await client.api<Me>("/auth/me"));
    return mfaToken;
  }, []);

  const completeMfa = useCallback(async (mfaToken: string, code: string) => {
    await client.loginTotp(mfaToken, code);
    setMe(await client.api<Me>("/auth/me"));
  }, []);

  const signOut = useCallback(async () => {
    await client.logout();
    setMe(null);
  }, []);

  return <Ctx.Provider value={{ me, loading, signIn, completeMfa, signOut, setMe }}>{children}</Ctx.Provider>;
}

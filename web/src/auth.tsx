import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import * as client from "./api";
import type { Me } from "./api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  setMe: (me: Me) => void;
}

const Ctx = createContext<AuthState>(null!);
export const useAuth = () => useContext(Ctx);

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
    await client.login(email, password);
    setMe(await client.api<Me>("/auth/me"));
  }, []);

  const signOut = useCallback(async () => {
    await client.logout();
    setMe(null);
  }, []);

  return <Ctx.Provider value={{ me, loading, signIn, signOut, setMe }}>{children}</Ctx.Provider>;
}

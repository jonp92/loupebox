import { useEffect, useState } from "react";
import { api } from "./api";

interface Policy {
  passwordMinLength: number;
  requireTotp: boolean;
}
const FALLBACK: Policy = { passwordMinLength: 12, requireTotp: false };
let cached: Promise<Policy> | null = null;

/** The server's sign-in policy (system settings), from the public features endpoint. */
export function usePolicy(): Policy {
  const [policy, setPolicy] = useState(FALLBACK);
  useEffect(() => {
    cached ??= api<{ password_min_length: number; require_totp: boolean }>("/auth/features").then(
      (f) => ({ passwordMinLength: f.password_min_length, requireTotp: f.require_totp }),
      () => FALLBACK,
    );
    cached.then(setPolicy);
  }, []);
  return policy;
}

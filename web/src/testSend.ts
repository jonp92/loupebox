import { api, json } from "./api";
import type { useToast } from "./toast";

/** POST a test-send endpoint and say what happened. `to` is the address a test email went to, if any. */
export async function sendTest(path: string, toast: ReturnType<typeof useToast>, body?: unknown) {
  try {
    const r = await api<{ status: string; error: string | null; to: string | null }>(
      path, body ? json("POST", body) : { method: "POST" },
    );
    const text = r.status === "sent" ? (r.to ? `Test sent to ${r.to}` : "Test delivered") : `Test ${r.status}: ${r.error ?? "unknown error"}`;
    (r.status === "sent" ? toast.success : toast.error)(text);
  } catch (e) {
    toast.error((e as Error).message);
  }
}

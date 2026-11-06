import { useEffect, useState } from "react";
import { api, type ProviderInfo, type SystemSetting } from "../api";
import { sendTest } from "../testSend";
import { useToast } from "../toast";

/** One "Send test" per email provider, to the signed-in superadmin. Reloads when settings are saved. */
export default function SystemTestEmail({ settings }: { settings: SystemSetting[] | null }) {
  const toast = useToast();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [sending, setSending] = useState<string | null>(null);
  useEffect(() => {
    api<ProviderInfo[]>("/notifications/providers").then((all) => setProviders(all.filter((p) => p.uses_recipients)));
  }, [settings]);

  async function test(p: ProviderInfo) {
    setSending(p.key);
    await sendTest("/system/test-email", toast, { provider: p.key });
    setSending(null);
  }

  if (!providers.length) return null;
  return (
    <section className="card" aria-labelledby="test-email-title">
      <h2 id="test-email-title">Send a test email</h2>
      <p className="hint muted">Goes to your own address through the provider you pick. Save any changes first.</p>
      <ul className="checklist">
        {providers.map((p) => (
          <li key={p.key}>
            <span className={`badge ${p.configured ? "read" : "pending"}`}>{p.configured ? "Ready" : "Not set up"}</span>
            <span className="grow">{p.label}</span>
            <button type="button" onClick={() => test(p)} disabled={!p.configured || sending !== null}>
              {sending === p.key ? "Sending…" : "Send test to me"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

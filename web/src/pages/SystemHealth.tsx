import { useCallback, useEffect, useState } from "react";
import { api, type HealthStatus, type InstanceHealth } from "../api";
import { ago } from "../triage";

const REFRESH_MS = 30_000;
// Text as well as color, and reuses the existing badge colors (ok / warn / danger).
const BADGE: Record<HealthStatus, { cls: string; text: string }> = {
  ok: { cls: "read", text: "Healthy" },
  warn: { cls: "pending", text: "Attention" },
  error: { cls: "failed", text: "Down" },
};

function Check({ title, status, children }: { title: string; status: HealthStatus; children: React.ReactNode }) {
  return (
    <div className="stat">
      <span className="muted">{title}</span>
      <span><span className={`badge ${BADGE[status].cls}`}>{BADGE[status].text}</span></span>
      <span className="hint muted">{children}</span>
    </div>
  );
}

const seen = (iso: string) => (ago(iso) === "now" ? "just now" : `${ago(iso)} ago`);
const wait = (s: number) => (s < 90 ? `${s}s` : `${Math.round(s / 60)}m`);

/** Is the database up, is the worker beating, is the outbox draining. Refreshes itself while visible. */
export default function SystemHealth() {
  const [health, setHealth] = useState<InstanceHealth | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api<InstanceHealth>("/system/health").then((h) => { setHealth(h); setError(""); }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  const { worker, outbox } = health ?? {};
  return (
    <section aria-labelledby="health-title">
      <div className="page-head">
        <h2 id="health-title">Instance health</h2>
        <button type="button" onClick={load}>Refresh</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {health && worker && outbox && (
        <div className="stats">
          <Check title="Database" status={health.database}>Answering queries.</Check>
          <Check title="Worker" status={worker.status}>
            {worker.last_beat_at
              ? `Last seen ${seen(worker.last_beat_at)}${worker.live ? `, ${worker.live} running` : ""}.`
              : <>Never seen. Nothing is sent without <code>python -m app.worker</code>.</>}
          </Check>
          <Check title="Outbox" status={outbox.status}>
            {outbox.pending} waiting
            {outbox.oldest_due_seconds != null && `, oldest ${wait(outbox.oldest_due_seconds)}`}.{" "}
            {outbox.held} held, {outbox.failed_24h} failed in 24 h.
          </Check>
          {health.redis && (
            <Check title="Redis" status={health.redis}>
              {health.redis === "ok"
                ? "Rate limits are shared between API containers."
                : "Unreachable. Each API container limits on its own until it is back."}
            </Check>
          )}
        </div>
      )}
    </section>
  );
}

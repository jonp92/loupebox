import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type HealthStatus, type InstanceHealth } from "../api";
import { ago } from "../triage";
import { Icon } from "../icons";
import { Status, type StatusTone } from "../ui/Status";

const REFRESH_MS = 30_000;
// A mark and a word, never color alone. There is no warning color: caution is a muted mark with a label.
const BADGE: Record<HealthStatus, { tone: StatusTone; text: string }> = {
  ok: { tone: "ok", text: "Healthy" },
  warn: { tone: "muted", text: "Attention" },
  error: { tone: "danger", text: "Down" },
};

function Check({ title, status, children }: { title: string; status: HealthStatus; children: React.ReactNode }) {
  return (
    <li className="check-row">
      <span className="ruled-main-col">
        <strong>{title}</strong>
        <span className="check-detail">{children}</span>
      </span>
      <Status tone={BADGE[status].tone}>{BADGE[status].text}</Status>
    </li>
  );
}

const since = (iso: string) => (ago(iso) === "now" ? "just now" : `${ago(iso)} ago`);
// What each checklist item asks for, and where to do it.
const STEPS: Record<InstanceHealth["checklist"][number]["id"], { label: string; to?: string }> = {
  mail: { label: "Set up an email provider", to: "/system/email" },
  public_url: { label: "Set the admin UI address", to: "/system/email" },
  worker: { label: "Start the worker (python -m app.worker)" },
  site: { label: "Create a site", to: "/sites" },
  channel: { label: "Add a notification channel to a site", to: "/sites" },
};

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
      <div className="section-head">
        <div>
          <h2 id="health-title">Instance health</h2>
          {health && worker && outbox && <p className="muted section-sub">{[health.database, worker.status, outbox.status, health.redis].filter((x) => x === "ok").length} of {health.redis ? 4 : 3} services healthy</p>}
        </div>
        <button type="button" onClick={load}><Icon name="refresh" size={18} />Refresh</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {health && worker && outbox && (
        <ul className="ruled">
          <Check title="Database" status={health.database}>Connected</Check>
          <Check title="Worker" status={worker.status}>
            {worker.last_beat_at
              ? `Last seen ${since(worker.last_beat_at)}${worker.live ? `, ${worker.live} running` : ""}`
              : "Never seen"}
          </Check>
          <Check title="Outbox" status={outbox.status}>
            {outbox.pending} waiting
            {outbox.oldest_due_seconds != null && ` (oldest ${wait(outbox.oldest_due_seconds)})`},{" "}
            {outbox.held} held, {outbox.failed_24h} failed in 24 h
          </Check>
          {health.redis && (
            <Check title="Redis" status={health.redis}>
              {health.redis === "ok" ? "Connected" : "Unreachable, rate limits are per API container"}
            </Check>
          )}
        </ul>
      )}
      {outbox && outbox.recent_failures.length > 0 && (
        <>
          <h3 id="failures-title" className="section-label">Recent failures</h3>
          <ul className="ruled failures" aria-labelledby="failures-title">
            {outbox.recent_failures.map((f, i) => (
              <li key={i}>
                <strong>{f.site}</strong>
                <span className="check-detail">
                  {f.channel ? `${f.channel} (${f.provider})` : "deleted channel"}, queued {since(f.queued_at)}, {f.attempts}{" "}
                  {f.attempts === 1 ? "attempt" : "attempts"}
                </span>
                <code>{f.error || "No error recorded"}</code>
              </li>
            ))}
          </ul>
        </>
      )}
      {health && health.checklist.some((i) => !i.done) && (
        <>
          <h3 id="checklist-title" className="section-label">Finish setting up</h3>
          <ul className="ruled checklist" aria-labelledby="checklist-title">
            {health.checklist.map(({ id, done }) => (
              <li key={id}>
                <Status tone={done ? "ok" : "muted"}>{done ? "Done" : "To do"}</Status>
                {!done && STEPS[id].to ? <Link to={STEPS[id].to}>{STEPS[id].label}</Link> : <span>{STEPS[id].label}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

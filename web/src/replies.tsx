import { type FormEvent, useEffect, useState } from "react";
import { api, json, type Feedback, type Reply, type ReplyThread } from "./api";

const MAX = 5000;

/** a•••@example.com: enough to recognise the address without putting it on screen in full. */
export const maskEmail = (email: string) => email.replace(/^(.).*(@.*)$/, "$1•••$2");

/** The conversation with the person who sent the item, and a form to answer them by email. */
export function Replies({ siteId, item, canEdit }: { siteId: string; item: Pick<Feedback, "id" | "email">; canEdit: boolean }) {
  const base = `/sites/${siteId}/feedback/${item.id}/replies`;
  const [thread, setThread] = useState<ReplyThread | null>(null);
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<ReplyThread>(base).then(setThread, (e) => setError(e.message)); }, [base]);

  const replace = (r: Reply) => setThread((t) => t && { ...t, items: t.items.map((x) => (x.id === r.id ? r : x)) });

  async function run(request: () => Promise<Reply>, done: (r: Reply) => void) {
    setSending(true);
    setError("");
    try {
      done(await request());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  }
  const send = (e: FormEvent) => {
    e.preventDefault();
    return run(() => api<Reply>(base, json("POST", { body })), (r) => {
      setThread((t) => t && { ...t, items: [...t.items, r] });
      setBody("");
    });
  };
  const retry = (id: string) => run(() => api<Reply>(`${base}/${id}/retry`, { method: "POST" }), replace);

  const blocked = !item.email
    ? "No email address was left with this feedback, so there is nobody to reply to."
    : thread && !thread.available && "Replies need a mail provider, which is not configured on this server.";
  if (!item.email && !thread?.items.length) return <p className="muted replies-off">{blocked}</p>;
  return (
    <section className="replies" aria-labelledby="replies-h">
      <h2 id="replies-h">Replies{item.email && <span className="muted"> · to {maskEmail(item.email)}</span>}</h2>
      {thread?.items.length === 0 && <p className="muted">No replies yet.</p>}
      <ul>
        {(thread?.items ?? []).map((r) => (
          <li key={r.id} className={r.status}>
            <span className="muted">{r.author_name ?? "Someone who has left"} · {new Date(r.created_at).toLocaleString()}</span>
            {/* Rendered as text by React; never as HTML. */}
            <p>{r.body}</p>
            {r.status === "sent" ? (
              <span className="muted">Accepted by the mail server</span>
            ) : (
              <span className="error">
                Not sent{r.error ? `: ${r.error}` : ""}.{" "}
                {r.retryable && canEdit && <button type="button" className="link" disabled={sending} onClick={() => retry(r.id)}>Try again</button>}
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="error" role="alert">{error}</p>
      {blocked ? <p className="muted">{blocked}</p> : canEdit && (
        <form onSubmit={send}>
          <label htmlFor="reply-body">Your reply</label>
          <textarea id="reply-body" value={body} onChange={(e) => setBody(e.target.value)} maxLength={MAX} disabled={sending} required />
          <div className="reply-foot">
            <span className="muted" aria-live="polite">{sending ? "Sending…" : `${body.length}/${MAX}`}</span>
            <button disabled={sending || !body.trim()}>{sending ? "Sending…" : "Send reply"}</button>
          </div>
        </form>
      )}
    </section>
  );
}

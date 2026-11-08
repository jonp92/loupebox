import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api, json, type Feedback, type Note, type Reply, type ReplyThread } from "./api";
import { Icon } from "./icons";
import { Bar, Placeholder } from "./Skeleton";
import { useToast } from "./toast";
import { Badge } from "./ui/Badge";

const MAX = { reply: 5000, note: 2000 };

type Kind = "reply" | "note";
type Entry = ({ kind: "reply" } & Reply) | ({ kind: "note" } & Note);

/**
 * One timeline for the whole discussion: what the person wrote back, what the team sent them, and the team's
 * private notes. A selector on the form picks which of the last two a new entry is. Viewers read everything;
 * editors write; a note's author or an admin deletes it.
 */
export function Conversation({ siteId, item, canEdit, canDeleteAny, meId }: {
  siteId: string; item: Pick<Feedback, "id" | "email">; canEdit: boolean; canDeleteAny: boolean; meId: string;
}) {
  const base = `/sites/${siteId}/feedback/${item.id}`;
  const toast = useToast();
  const [thread, setThread] = useState<ReplyThread | null>(null);
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [kind, setKind] = useState<Kind | null>(null);
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api<ReplyThread>(`${base}/replies`).then(setThread, (e) => setError(e.message));
    api<Note[]>(`${base}/notes`).then(setNotes, (e) => setError(e.message));
  }, [base]);

  const entries = useMemo<Entry[]>(
    () => [
      ...(thread?.items ?? []).map((r) => ({ kind: "reply" as const, ...r })),
      ...(notes ?? []).map((n) => ({ kind: "note" as const, ...n })),
    ].sort((a, b) => a.created_at.localeCompare(b.created_at)),
    [thread, notes],
  );

  const replyBlock = !item.email
    ? "No email address was left with this feedback, so there is nobody to reply to."
    : thread && !thread.available ? "Replies need a mail provider, which is not configured on this server." : "";
  // Default to a reply when one can be sent; a note is always possible.
  const current: Kind = replyBlock ? "note" : (kind ?? "reply");

  const replace = (r: Reply) => setThread((t) => t && { ...t, items: t.items.map((x) => (x.id === r.id ? r : x)) });
  async function sendReply(request: () => Promise<Reply>, done: (r: Reply) => void) {
    setSending(true);
    try {
      const r = await request();
      done(r);
      if (r.status === "sent") toast.success("Reply sent");
      else toast.error(`Reply not sent${r.error ? `: ${r.error}` : ""}`);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSending(false);
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (current === "reply") {
      return sendReply(() => api<Reply>(`${base}/replies`, json("POST", { body })), (r) => {
        setThread((t) => t && { ...t, items: [...t.items, r] });
        setBody("");
      });
    }
    setSending(true);
    await toast.attempt(
      api<Note>(`${base}/notes`, json("POST", { body })).then((n) => {
        setNotes((cur) => [...(cur ?? []), n]);
        setBody("");
      }),
      "Note added",
    );
    setSending(false);
  }
  const retry = (id: string) => sendReply(() => api<Reply>(`${base}/replies/${id}/retry`, { method: "POST" }), replace);
  const removeNote = (id: string) => toast.attempt(
    api(`${base}/notes/${id}`, { method: "DELETE" }).then(() => setNotes((cur) => (cur ?? []).filter((n) => n.id !== id))),
    "Note deleted",
  );

  const loading = !error && (thread === null || notes === null);
  const max = MAX[current];
  const verb = current === "reply" ? "Send reply" : "Add note";
  return (
    <section className="convo" aria-labelledby="convo-h">
      <h2 id="convo-h">Conversation</h2>
      {loading ? (
        <Placeholder label="Loading the conversation…"><Bar w="60%" /><Bar w="85%" /></Placeholder>
      ) : (
        <>
          {entries.length === 0 && <p className="muted">Nothing yet.</p>}
          <ul>
            {entries.map((e) => <Item key={`${e.kind}-${e.id}`} e={e} canEdit={canEdit} busy={sending}
              canDelete={e.kind === "note" && (e.author_id === meId || canDeleteAny)} onRetry={retry} onDelete={removeNote} />)}
          </ul>
        </>
      )}
      <p className="error" role="alert">{error}</p>
      {canEdit && !loading && (
        <form onSubmit={submit}>
          <div className="convo-kind">
            <label htmlFor="convo-kind">Add</label>
            <select id="convo-kind" value={current} onChange={(e) => setKind(e.target.value as Kind)} disabled={sending}>
              <option value="reply" disabled={!!replyBlock}>Reply to customer (email)</option>
              <option value="note">Internal note</option>
            </select>
            <span className="muted">
              {current === "reply"
                ? `Emailed to ${item.email}${thread?.inbound ? ". Their answer comes back here" : ""}`
                : "Only your team sees this"}
            </span>
          </div>
          {replyBlock && <p className="muted">{replyBlock}</p>}
          <textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={max} disabled={sending}
            aria-label={current === "reply" ? "Your reply" : "New note"} required />
          <div className="convo-foot">
            <span className="muted" aria-live="polite">{sending ? "Sending…" : `${body.length}/${max}`}</span>
            <button disabled={sending || !body.trim()}>{sending ? "Sending…" : verb}</button>
          </div>
        </form>
      )}
    </section>
  );
}

function Item({ e, canEdit, canDelete, busy, onRetry, onDelete }: {
  e: Entry; canEdit: boolean; canDelete: boolean; busy: boolean;
  onRetry: (id: string) => void; onDelete: (id: string) => void;
}) {
  const label = e.kind === "note" ? "Internal note" : e.direction === "inbound" ? "Customer" : "Reply";
  const who = e.kind === "reply" && e.direction === "inbound" ? null : (e.author_name ?? "Someone who has left");
  return (
    <li className={`convo-${e.kind === "note" ? "note" : e.direction}${e.kind === "reply" && e.status === "failed" ? " failed" : ""}`}>
      <span className="convo-meta">
        <Badge plain><Icon name={e.kind === "note" ? "note" : e.direction === "inbound" ? "person" : "reply"} size={14} />{label}</Badge>
        <span className="muted" title={new Date(e.created_at).toLocaleString()}>
          {who && `${who} · `}{new Date(e.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
        </span>
        {canDelete && (
          <button type="button" className="icon plain convo-del" aria-label="Delete note" onClick={() => onDelete(e.id)}><Icon name="trash" size={18} /></button>
        )}
      </span>
      {/* Rendered as text by React; never as HTML. */}
      <p>{e.body}</p>
      {e.kind === "reply" && e.direction === "outbound" && (e.status === "sent" ? (
        <span className="muted">Accepted by the mail server</span>
      ) : (
        <span className="error">
          Not sent{e.error ? `: ${e.error}` : ""}.{" "}
          {e.retryable && canEdit && <button type="button" className="link" disabled={busy} onClick={() => onRetry(e.id)}>Try again</button>}
        </span>
      ))}
    </li>
  );
}

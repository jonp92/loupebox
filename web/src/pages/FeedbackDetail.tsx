import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json, type Feedback, type Site, type Status } from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";
import { Attachments } from "../attachments";
import { Replies } from "../replies";
import { FeedbackBadges, Notes, Tags, below, safeHref, useAssigneePicker } from "../triage";

const STATUSES: Status[] = ["new", "read", "archived", "spam"];

/** One feedback item with everything about it: contact details, metadata, triage and the team's notes. */
export default function FeedbackDetail({ site }: { site: Site }) {
  const { feedbackId } = useParams();
  const { me } = useAuth();
  const confirm = useConfirm();
  const toast = useToast();
  const navigate = useNavigate();
  const picker = useAssigneePicker(site.id);
  const [item, setItem] = useState<Feedback | null>(null);
  const [error, setError] = useState("");
  const canEdit = site.my_role === "editor" || site.my_role === "admin";
  const canDelete = site.my_role === "admin";
  const path = `/sites/${site.id}/feedback/${feedbackId}`;

  const load = useCallback(() => {
    api<Feedback>(path).then((f) => { setItem(f); setError(""); }, (e) => { setItem(null); setError(e.message); });
  }, [path]);
  useEffect(load, [load]);

  async function patch(body: Partial<{ status: Status; assignee_id: string | null; tags: string[] }>) {
    await toast.attempt(api(path, json("PATCH", body)));
    load();
  }
  async function remove() {
    if (!(await confirm({ title: "Delete this feedback?", message: "This cannot be undone.", confirmLabel: "Delete", danger: true }))) return;
    if (await toast.attempt(api(path, { method: "DELETE" }), "Feedback deleted")) navigate(`/sites/${site.id}`);
  }

  const href = item && safeHref(item.page_url);
  return (
    <>
      <p><Link to={`/sites/${site.id}`} className="back">← All feedback</Link></p>
      {error && <p className="error">{error}</p>}
      {item && (
        <article className={`card fb ${item.status}`}>
          <header>
            <FeedbackBadges f={item} />
            <span className="muted grow-end">{new Date(item.created_at).toLocaleString()}</span>
          </header>
          {/* Rendered as text by React; never as HTML. */}
          <p className="message">{item.message}</p>
          <p className="muted">
            {[item.name, item.email].filter(Boolean).join(" · ")}
            {href && <> · <a href={href} target="_blank" rel="noopener noreferrer">{href}</a></>}
          </p>
          {item.attachment_count > 0 && <Attachments siteId={site.id} item={item} canDelete={canDelete} onChange={load} />}
          {Object.keys(item.metadata).length > 0 && <pre>{JSON.stringify(item.metadata, null, 2)}</pre>}
          <div className="tags-row">
            <Tags item={item} canEdit={canEdit} onChange={(tags) => patch({ tags })} />
            {canEdit ? (
              <button className="assign" onClick={(e) => picker.open(below(e.currentTarget), item.assignee_id, (p) => patch({ assignee_id: p?.user_id ?? null }))}>
                👤 {item.assignee_name ?? "Assign…"}
              </button>
            ) : item.assignee_name && <span className="assign muted">👤 {item.assignee_name}</span>}
          </div>
          {canEdit && (
            <div className="actions">
              {STATUSES.filter((s) => s !== item.status).map((s) => <button key={s} onClick={() => patch({ status: s })}>Mark {s}</button>)}
              {canDelete && <button className="danger" onClick={remove}>Delete</button>}
            </div>
          )}
          <Replies siteId={site.id} item={item} canEdit={canEdit} />
          {me && <Notes siteId={site.id} itemId={item.id} canEdit={canEdit} canDeleteAny={canDelete} meId={me.id} />}
        </article>
      )}
      {picker.node}
    </>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, json, type Feedback, type Site, type Status } from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";
import { Attachments } from "../attachments";
import { Conversation } from "../replies";
import { MetadataList } from "../metadata";
import { FeedbackBadges, Tags, below, safeHref, useAssigneePicker, useContextMenu, type MenuItem } from "../triage";
import { Icon } from "../icons";
import { Bar, Placeholder } from "../Skeleton";
import { useLive } from "../live";

const STATUSES: Status[] = ["new", "read", "archived", "spam"];

/** One feedback item with everything about it: contact details, metadata, triage and the team's notes. */
export default function FeedbackDetail({ site }: { site: Site }) {
  const { feedbackId } = useParams();
  const { me } = useAuth();
  const confirm = useConfirm();
  const toast = useToast();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from; // the list the item was opened from
  const picker = useAssigneePicker(site.id);
  const ctx = useContextMenu();
  const [item, setItem] = useState<Feedback | null>(null);
  const [error, setError] = useState("");
  const canEdit = site.my_role === "editor" || site.my_role === "admin";
  const canDelete = site.my_role === "admin";
  const path = `/sites/${site.id}/feedback/${feedbackId}`;

  const load = useCallback(() => {
    api<Feedback>(path).then((f) => { setItem(f); setError(""); }, (e) => { setItem(null); setError(e.message); });
  }, [path]);
  useEffect(load, [load]);
  useLive(load, (e) => e.feedback_id === feedbackId);

  async function patch(body: Partial<{ status: Status; assignee_id: string | null; tags: string[] }>) {
    await toast.attempt(api(path, json("PATCH", body)));
    load();
  }
  async function remove() {
    if (!(await confirm({ title: "Delete this feedback?", message: "This cannot be undone.", confirmLabel: "Delete", danger: true }))) return;
    if (await toast.attempt(api(path, { method: "DELETE" }), "Feedback deleted")) navigate(from ?? `/sites/${site.id}`);
  }

  const others = item ? STATUSES.filter((st) => st !== item.status) : [];
  const next: Status = item?.status === "new" ? "read" : item?.status === "read" ? "archived" : "read";
  const moreMenu: MenuItem[] = [
    ...others.filter((st) => st !== next).map((st) => ({ label: `Mark ${st}`, onSelect: () => patch({ status: st }) })),
    ...(canDelete ? [{ label: "Delete", danger: true, onSelect: remove }] : []),
  ];
  const href = item && safeHref(item.page_url);
  return (
    <>
      <p><Link to={from ?? `/sites/${site.id}`} className="back"><Icon name="arrow-left" size={16} />{from ? "Back to the list" : "All feedback"}</Link></p>
      {error && <p className="error">{error}</p>}
      {!item && !error && (
        <Placeholder label="Loading feedback">
          <div className="card ph"><Bar w="7rem" h=".8rem" /><Bar w="80%" /><Bar w="60%" /></div>
        </Placeholder>
      )}
      {item && (
        <article className={`card fb ${item.status}`}>
          <header>
            <span className="fb-badges"><FeedbackBadges f={item} /></span>
            <time className="grow-end" dateTime={item.created_at} title={new Date(item.created_at).toLocaleString()}>{new Date(item.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</time>
          </header>
          {/* Rendered as text by React; never as HTML. */}
          <p className="message">{item.message}</p>
          <p className="person">
            {[item.name, item.email].filter(Boolean).join(" · ")}
            {href && <> · <a href={href} target="_blank" rel="noopener noreferrer">{href}</a></>}
          </p>
          {item.attachment_count > 0 && <Attachments siteId={site.id} item={item} canDelete={canDelete} onChange={load} />}
          <MetadataList metadata={item.metadata} />
          <div className="tags-row">
            <Tags item={item} canEdit={canEdit} onChange={(tags) => patch({ tags })} />
            {canEdit ? (
              <button className="assign" onClick={(e) => picker.open(below(e.currentTarget), item.assignee_id, (p) => patch({ assignee_id: p?.user_id ?? null }))}>
                <Icon name="person" size={16} />{item.assignee_name ?? "Assign…"}
              </button>
            ) : item.assignee_name && <span className="assign muted"><Icon name="person" size={16} />{item.assignee_name}</span>}
          </div>
          {canEdit && (
            <div className="actions">
              <span className="actions-wide">
                {others.map((st) => <button key={st} onClick={() => patch({ status: st })}>Mark {st}</button>)}
                {canDelete && <button className="danger" onClick={remove}>Delete</button>}
              </span>
              {/* Phones: the likely next step stays one tap away, the rest sit behind a menu. */}
              <span className="actions-narrow">
                <button className="primary" onClick={() => patch({ status: next })}>Mark {next}</button>
                <button className="menu-btn" aria-label="More actions" aria-haspopup="menu" onClick={(e) => ctx.openAt(e.currentTarget, moreMenu)}><Icon name="more" /></button>
              </span>
            </div>
          )}
          {me && <Conversation siteId={site.id} item={item} canEdit={canEdit} canDeleteAny={canDelete} meId={me.id} />}
        </article>
      )}
      {picker.node}
      {ctx.node}
    </>
  );
}

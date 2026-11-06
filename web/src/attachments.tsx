import { useEffect, useRef, useState } from "react";
import { api, fetchBlob, type Attachment, type Feedback } from "./api";
import { useConfirm } from "./confirm";
import { Bar, Placeholder } from "./Skeleton";
import { useToast } from "./toast";

/** An image from the API. An <img src> cannot send the login token, so it is fetched and shown from an object URL. */
function useBlobUrl(path: string) {
  const [state, setState] = useState<{ url?: string; failed?: boolean }>({});
  useEffect(() => {
    setState({});
    let url: string | undefined;
    let stale = false;
    fetchBlob(path).then(
      (blob) => {
        if (stale) return;
        url = URL.createObjectURL(blob);
        setState({ url });
      },
      () => !stale && setState({ failed: true }),
    );
    return () => {
      stale = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);
  return state;
}

function Picture({ path, alt }: { path: string; alt: string }) {
  const { url, failed } = useBlobUrl(path);
  if (failed) return <span className="muted">Could not load the image.</span>;
  return url ? <img src={url} alt={alt} /> : <span className="skeleton" role="status" aria-label="Loading image" />;
}

function Viewer({ base, items, index, canDelete, onIndex, onClose, onDelete }: {
  base: string;
  items: Attachment[];
  index: number;
  canDelete: boolean;
  onIndex: (i: number) => void;
  onClose: () => void;
  onDelete: (a: Attachment) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => dialog.current?.showModal(), []);
  const current = items[index];
  const go = (step: number) => onIndex(Math.min(items.length - 1, Math.max(0, index + step)));
  return (
    <dialog
      ref={dialog}
      className="lightbox"
      aria-label={`Image ${index + 1} of ${items.length}`}
      onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === dialog.current) onClose(); }}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") go(-1);
        else if (e.key === "ArrowRight") go(1);
      }}
    >
      {/* The dialog has a fixed size, so the buttons stay where they are as pictures load or change, and sit
          under the picture where a hand does not cover it. */}
      <div className="lightbox-image">
        <Picture key={current.id} path={`${base}/${current.id}`} alt={`Image ${index + 1} of ${items.length} sent with this feedback`} />
      </div>
      <div className="lightbox-bar">
        <span className="muted" aria-live="polite">{index + 1} / {items.length}</span>
        <span className="row-actions">
          <button onClick={() => go(-1)} disabled={index === 0}>Previous</button>
          <button onClick={() => go(1)} disabled={index === items.length - 1}>Next</button>
          {canDelete && <button className="danger" onClick={() => onDelete(current)}>Delete image</button>}
          <button autoFocus onClick={onClose}>Close</button>
        </span>
      </div>
    </dialog>
  );
}

/** The images a visitor sent with an item: a thumbnail grid, each opening a full-size viewer. */
export function Attachments({ siteId, item, canDelete, onChange }: {
  siteId: string;
  item: Pick<Feedback, "id" | "attachment_count">;
  canDelete: boolean;
  onChange: () => void;
}) {
  const base = `/sites/${siteId}/feedback/${item.id}/attachments`;
  const confirm = useConfirm();
  const toast = useToast();
  const [items, setItems] = useState<Attachment[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const latest = useRef(0);
  const thumbs = useRef<(HTMLButtonElement | null)[]>([]);
  const lastViewed = useRef<number | null>(null);

  // The viewer is unmounted, not closed, so the browser does not hand focus back: do it here, to the last image seen.
  useEffect(() => {
    if (open !== null) lastViewed.current = open;
    else if (lastViewed.current !== null) {
      thumbs.current[lastViewed.current]?.focus();
      lastViewed.current = null;
    }
  }, [open]);

  useEffect(() => {
    const n = ++latest.current;
    api<Attachment[]>(base).then(
      (rows) => n === latest.current && setItems(rows),
      (e) => n === latest.current && setError(e.message),
    );
  }, [base, item.attachment_count]); // a deleted image changes the count, which reloads the list in place

  async function remove(a: Attachment) {
    if (!(await confirm({
      title: "Delete this image?",
      message: "The message and its other images are kept. This cannot be undone.",
      confirmLabel: "Delete",
      danger: true,
    }))) return;
    if (await toast.attempt(api(`${base}/${a.id}`, { method: "DELETE" }), "Image deleted")) {
      setOpen(null);
      onChange();
    }
  }

  return (
    <section aria-labelledby={`img-${item.id}`}>
      <h3 id={`img-${item.id}`} className="section-title">Images ({item.attachment_count})</h3>
      {error && <p className="error">{error}</p>}
      {!items && !error && (
        <Placeholder label="Loading images…">
          <div className="thumbs">{Array.from({ length: item.attachment_count }, (_, i) => <Bar key={i} w="8rem" h="6rem" />)}</div>
        </Placeholder>
      )}
      {items && (
        <div className="thumbs">
          {items.map((a, i) => (
            <button key={a.id} ref={(el) => { thumbs.current[i] = el; }} className="thumb" aria-label={`View image ${i + 1} of ${items.length}`} onClick={() => setOpen(i)}>
              <Picture path={`${base}/${a.id}`} alt="" />
            </button>
          ))}
        </div>
      )}
      {items && open !== null && items[open] && (
        <Viewer base={base} items={items} index={open} canDelete={canDelete} onIndex={setOpen} onClose={() => setOpen(null)} onDelete={remove} />
      )}
    </section>
  );
}

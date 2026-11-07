import { useEffect, useId, useRef, type ReactNode } from "react";
import { Icon } from "../icons";

/**
 * A modal for create flows: a bottom sheet on phones, a centered dialog from 640px up. It is a native <dialog>, so
 * the browser traps focus, makes the page behind inert and closes it on Escape. The children are only mounted while
 * it is open, so a form inside starts empty every time.
 */
export function Sheet({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      d.querySelector<HTMLElement>("input, select, textarea")?.focus(); // the first field, not the close button
    } else if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog ref={dialog} className="sheet" aria-labelledby={titleId} onClose={onClose}
      onClick={(e) => { if (e.target === dialog.current) onClose(); }}>
      <div className="sheet-grab" aria-hidden />
      <div className="sheet-head">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="icon plain" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
      </div>
      {open && children}
    </dialog>
  );
}

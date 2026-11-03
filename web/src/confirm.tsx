import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  danger?: boolean;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm>(() => Promise.resolve(false));

/** Promise-based replacement for window.confirm: `if (!(await confirm({ title: "..." }))) return;` */
export const useConfirm = () => useContext(ConfirmContext);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  const confirm = useCallback<Confirm>(
    (options) => new Promise<boolean>((resolve) => setPending({ ...options, resolve })),
    [],
  );

  useEffect(() => {
    if (pending && !dialog.current?.open) dialog.current?.showModal();
  }, [pending]);

  function close(ok: boolean) {
    pending?.resolve(ok);
    dialog.current?.close();
    setPending(null);
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <dialog
          ref={dialog}
          className="confirm"
          aria-labelledby="confirm-title"
          onCancel={(e) => { e.preventDefault(); close(false); }}
          onClick={(e) => { if (e.target === dialog.current) close(false); }}
        >
          <h2 id="confirm-title">{pending.title}</h2>
          {pending.message && <p className="muted">{pending.message}</p>}
          <div className="row-actions">
            <button autoFocus onClick={() => close(false)}>Cancel</button>
            <button className={pending.danger ? "danger" : "primary"} onClick={() => close(true)}>
              {pending.confirmLabel ?? "Confirm"}
            </button>
          </div>
        </dialog>
      )}
    </ConfirmContext.Provider>
  );
}

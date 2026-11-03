import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Kind = "success" | "error" | "info";

interface ToastOptions {
  /** Stays until dismissed. Errors do by default; everything else times out. */
  sticky?: boolean;
  /** Milliseconds before it goes away on its own. */
  duration?: number;
  /** One follow-up action, e.g. Undo or Retry. Dismisses the toast when clicked. */
  action?: { label: string; onClick: () => void };
}

interface ToastItem extends ToastOptions {
  id: number;
  kind: Kind;
  message: string;
}

interface Toasts {
  success: (message: string, options?: ToastOptions) => void;
  error: (message: string, options?: ToastOptions) => void;
  info: (message: string, options?: ToastOptions) => void;
  /** Await `work`, toasting `success` if given or the error message on failure. Resolves to whether it worked. */
  attempt: (work: Promise<unknown>, success?: string) => Promise<boolean>;
}

const noop = () => undefined;
const ToastContext = createContext<Toasts>({ success: noop, error: noop, info: noop, attempt: () => Promise.resolve(false) });

/** `toast.success("Saved")`, `toast.error(err.message)`, or `await toast.attempt(api(...), "Saved")`. */
export const useToast = () => useContext(ToastContext);

const DURATION = 4000;
const MAX_VISIBLE = 5;
let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((cur) => cur.filter((t) => t.id !== id)), []);

  const toasts = useMemo<Toasts>(() => {
    const show = (kind: Kind) => (message: string, options: ToastOptions = {}) =>
      setItems((cur) => [
        // The same message twice in a row is one toast, shown afresh.
        ...cur.filter((t) => t.message !== message || t.kind !== kind),
        { ...options, id: nextId++, kind, message, sticky: options.sticky ?? kind === "error" },
      ].slice(-MAX_VISIBLE));
    const error = show("error");
    return {
      success: show("success"),
      error,
      info: show("info"),
      attempt: async (work, success) => {
        try {
          await work;
          if (success) toasts.success(success);
          return true;
        } catch (e) {
          error((e as Error).message);
          return false;
        }
      },
    };
  }, []);

  return (
    <ToastContext.Provider value={toasts}>
      {children}
      <div className="toasts" role="region" aria-label="Notifications">
        {items.map((t) => <ToastView key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />)}
      </div>
    </ToastContext.Provider>
  );
}

function ToastView({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  // Hovering or focusing a toast holds its timer, so there is time to read it or reach its button.
  const [held, setHeld] = useState(false);
  useEffect(() => {
    if (toast.sticky || held) return;
    const t = setTimeout(onDismiss, toast.duration ?? DURATION);
    return () => clearTimeout(t);
  }, [toast.sticky, toast.duration, held, onDismiss]);

  return (
    <div
      className={`toast ${toast.kind}`}
      role={toast.kind === "error" ? "alert" : "status"}
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
    >
      <span className="toast-msg">{toast.message}</span>
      {toast.action && (
        <button type="button" className="link" onClick={() => { toast.action!.onClick(); onDismiss(); }}>
          {toast.action.label}
        </button>
      )}
      <button type="button" className="toast-close" aria-label="Dismiss" onClick={onDismiss}>×</button>
    </div>
  );
}

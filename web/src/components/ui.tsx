import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  pending?: boolean;
  pendingLabel?: string;
  variant?: "primary" | "secondary" | "danger" | "link";
};

/** Botón que se deshabilita mientras hay un envío en curso para evitar dobles envíos. */
export function Button({ pending = false, pendingLabel = "Procesando…", variant = "primary", children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={`btn btn-${variant}${rest.className ? ` ${rest.className}` : ""}`}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
    >
      {pending ? pendingLabel : children}
    </button>
  );
}

export function Alert({ tone = "info", title, children }: { tone?: "info" | "warning" | "error" | "success"; title?: string; children: ReactNode }) {
  const urgent = tone === "error" || tone === "warning";
  return (
    <div className={`alert alert-${tone}`} role={urgent ? "alert" : "status"}>
      {title && <p className="alert-title">{title}</p>}
      <div>{children}</div>
    </div>
  );
}

export function Loading({ label = "Cargando…" }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <p>{message}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Reintentar
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <section className="empty-state" aria-label={title}>
      <h2>{title}</h2>
      {children}
      {action}
    </section>
  );
}

/** Encabezado de página que recibe el foco al navegar, para lectores de pantalla y teclado. */
export function PageTitle({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <h1 ref={ref} tabIndex={-1} className="page-title">
      {children}
    </h1>
  );
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  onConfirm,
  onCancel,
  pending,
  danger,
  confirmDisabled,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  pending?: boolean;
  danger?: boolean;
  confirmDisabled?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className="dialog"
      onCancel={(e) => {
        e.preventDefault();
        if (!pending) onCancel();
      }}
    >
      <h2 id={titleId}>{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="actions">
        <Button variant="secondary" onClick={onCancel} disabled={pending}>
          Cancelar
        </Button>
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} pending={pending} disabled={confirmDisabled}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}

import type { ReactNode } from "react";

const labels: Record<string, string> = {
  pending_review: "Pending review",
  approved: "Approved",
  exported: "Exported",
  cancelled: "Cancelled",
  auto_accepted: "Auto accepted",
  needs_review: "Needs review",
  unresolved: "Unresolved",
  confirmed: "Confirmed",
  corrected: "Corrected",
};
export const label = (value: string) =>
  labels[value] || value.replaceAll("_", " ");
export function Badge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status}`}>
      <span aria-hidden="true">●</span> {label(status)}
    </span>
  );
}
export function Alert({
  message,
  onClose,
}: {
  message: string;
  onClose?: () => void;
}) {
  return message ? (
    <div className="alert" role="alert">
      <span>{message}</span>
      {onClose && (
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Dismiss error"
        >
          ×
        </button>
      )}
    </div>
  ) : null;
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Spinner() {
  return <span className="spinner" role="status" aria-label="Loading" />;
}
export const parseApiDate = (value: string) =>
  new Date(
    /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      ? value
      : `${value.replace(" ", "T")}Z`,
  );
export const dateTime = (value?: string | null) =>
  value ? parseApiDate(value).toLocaleString() : "—";
export const percent = (value: number) => `${Math.round(value * 100)}%`;

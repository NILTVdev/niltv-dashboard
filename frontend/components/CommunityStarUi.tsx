import { cn } from "@/lib/utils";

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="flex justify-between text-xs text-gray-500"><span>{label}</span>{hint && <span className="text-gray-400">{hint}</span>}</span>
      {children}
    </label>
  );
}

export function Chip({ children, tone = "default" }: { children: React.ReactNode; tone?: "default" | "ok" | "warn" | "bad" }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 ring-1",
      tone === "default" && "bg-white text-gray-700 ring-gray-200",
      tone === "ok" && "bg-emerald-50 text-emerald-800 ring-emerald-200",
      tone === "warn" && "bg-amber-50 text-amber-800 ring-amber-200",
      tone === "bad" && "bg-red-50 text-red-700 ring-red-200")}>
      {children}
    </span>
  );
}

export function Btn({ children, onClick, disabled, tone = "default", title }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean; tone?: "default" | "primary" | "danger"; title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition-colors disabled:opacity-50 max-sm:px-3 max-sm:py-2 max-sm:text-sm",
        tone === "primary" && "bg-[var(--brand)] text-white hover:opacity-90",
        tone === "danger" && "bg-red-600 text-white hover:bg-red-700",
        tone === "default" && "border text-gray-700 hover:bg-gray-50",
      )}
    >
      {children}
    </button>
  );
}

export function Banner({ children }: { children: React.ReactNode }) {
  return <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{children}</div>;
}

export function PanelTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">{children}</h3>;
}

export function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={cn("rounded-xl border bg-white p-4 shadow-sm", className)}>{children}</section>;
}

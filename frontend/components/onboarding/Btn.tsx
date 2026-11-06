import { cn } from "@/lib/utils";

export default function Btn({ children, onClick, disabled, tone = "default", title }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean; tone?: "default" | "primary" | "quiet"; title?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        // Bigger tap targets on a phone.
        "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition-colors disabled:opacity-50 max-sm:px-3 max-sm:py-2 max-sm:text-sm",
        tone === "primary" && "bg-[var(--brand)] text-white hover:opacity-90",
        tone === "quiet" && "text-gray-600 hover:bg-gray-100 hover:text-gray-900",
        tone === "default" && "border text-gray-700 hover:bg-gray-50",
      )}
    >
      {children}
    </button>
  );
}

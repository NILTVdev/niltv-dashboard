import { ChevronDown, ChevronUp, TriangleAlert } from "lucide-react";
import { cn, fmtDate } from "@/lib/utils";
import { STATUS_LABEL, STATUS_STYLE, waitingOn } from "@/lib/onboarding";
import type { Application, ApplicationStep } from "@/lib/types";
import Actions from "./Actions";
import Detail from "./Detail";

// One row of the table, and its detail panel when it's open.
export default function ApplicationRow({ row, open, selected, selectDisabled, busy, onToggle, onSelect, onRun }: {
  row: Application;
  open: boolean;
  selected: boolean;
  selectDisabled: boolean;
  busy: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onRun: (a: string, b?: unknown) => void;
}) {
  const wait = waitingOn(row);
  return (
    <>
      <tr className={cn("hover:bg-gray-50 cursor-pointer max-sm:grid max-sm:grid-cols-[auto_minmax(0,1fr)_auto] max-sm:py-1.5",
        open && "bg-[var(--brand-pale)]/40")} onClick={onToggle}>
        <td className="pl-3 py-2 max-sm:col-start-1 max-sm:row-start-1" onClick={(e) => e.stopPropagation()}>
          <input type="checkbox" aria-label={`Select ${row.first_name ?? ""} ${row.last_name ?? ""}`}
                 checked={selected} onChange={onSelect} disabled={selectDisabled} />
        </td>
        <td className="px-3 py-2 text-gray-400 max-sm:col-start-3 max-sm:row-start-1">{open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}</td>
        <td className="px-3 py-2 max-sm:col-start-2 max-sm:row-start-1 max-sm:pb-0.5">
          <div className="font-medium">{row.first_name} {row.last_name}</div>
          <div className="text-xs text-gray-500">
            {row.instagram ? `@${row.instagram}` : row.email}
            {row.international && <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600" title="International student (from the form)">INTL</span>}
          </div>
        </td>
        <td className="px-3 py-2 max-sm:col-start-2 max-sm:row-start-2 max-sm:py-0.5">
          <div>{row.university ?? <span className="text-gray-400">?</span>}</div>
          <div className="text-xs text-gray-500">{[row.sport, row.year].filter(Boolean).join(" · ")}</div>
        </td>
        <td className="px-3 py-2 max-sm:col-start-2 max-sm:row-start-3 max-sm:pt-1.5">
          <span className={cn("inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ring-1", STATUS_STYLE[row.status])}>
            {STATUS_LABEL[row.status]}
          </span>
          {wait && (
            <div className={cn("mt-1 flex max-w-[18rem] items-start gap-1 text-xs",
              wait.alert ? "font-medium text-amber-700" : "text-gray-600")}>
              {wait.alert && <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />}
              {wait.text}
            </div>
          )}
        </td>
        <td className="hidden px-3 py-2 lg:table-cell"><Progress steps={row.progress} /></td>
        <td className="hidden px-3 py-2 text-xs text-gray-500 whitespace-nowrap lg:table-cell">{fmtDate(row.created_at)}</td>
        <td className="px-3 py-2 text-right max-sm:col-span-2 max-sm:col-start-2 max-sm:row-start-4" onClick={(e) => e.stopPropagation()}>
          <Actions row={row} busy={busy} onRun={onRun} />
        </td>
      </tr>
      {open && (
        <tr className="bg-[var(--brand-pale)]/30 max-sm:block">
          <td colSpan={8} className="px-6 py-4 max-sm:block max-sm:px-4">
            <Detail row={row} busy={busy} onRun={onRun} />
          </td>
        </tr>
      )}
    </>
  );
}

// One plain dot per step: filled = done, ring = where the row is now, dash =
// skipped. The status line says the rest; the tooltip spells out each step.
const DOT: Record<ApplicationStep["state"], string> = {
  done: "bg-slate-600",
  current: "bg-white ring-2 ring-inset ring-slate-600",
  blocked: "bg-white ring-2 ring-inset ring-gray-300",
  skipped: "h-0.5 rounded-sm bg-gray-300",
  todo: "bg-gray-200",
};

function Progress({ steps }: { steps: ApplicationStep[] }) {
  const summary = steps.map((s) => `${s.label}: ${s.state}${s.detail ? ` (${s.detail})` : ""}`).join("\n");
  return (
    <div className="flex items-center gap-1.5" title={summary} role="img" aria-label={summary}>
      {steps.map((s) => <span key={s.key} className={cn("h-2 w-2 rounded-full", DOT[s.state])} />)}
    </div>
  );
}

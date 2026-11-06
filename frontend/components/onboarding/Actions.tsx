import { Check, RefreshCw, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Application } from "@/lib/types";
import Btn from "./Btn";

// Decline first, then the next step on the right: filled when the move is
// staff's (the amber pills), outlined when it only nudges the athlete.
// Refresh shows in the opened row only; the tab row's Refresh buttons cover
// the list.
export default function Actions({ row, busy, onRun, withRefresh = false }: {
  row: Application; busy: boolean; onRun: (a: string, b?: unknown) => void; withRefresh?: boolean;
}) {
  const s = row.status;
  const next = s === "applicant" || s === "approved" || s === "signed" ? "primary" : "default";
  const decline = () => {
    const reason = window.prompt("Decline reason (kept on the record; optional):", row.decline_reason ?? "");
    if (reason === null) return;
    const notify = window.confirm("Email the athlete that they were not selected?");
    onRun("decline", { reason, notify });
  };
  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      {(s === "applicant" || s === "approved" || s === "agreement_sent") && (
        <Btn tone="quiet" disabled={busy} onClick={decline}>Decline</Btn>
      )}
      {(s === "applicant" || s === "declined") && (
        <Btn tone={next} disabled={busy || row.missing_for_approval.length > 0}
             title={row.missing_for_approval.length ? `Missing: ${row.missing_for_approval.join(", ")}` : "Approve and send the agreement"}
             onClick={() => onRun("approve", { by: "staff" })}>
          <Check className="h-3.5 w-3.5" /> Approve
        </Btn>
      )}
      {(s === "approved" || s === "agreement_sent") && (
        <Btn tone={next} disabled={busy} onClick={() => onRun("resend-agreement")} title="Create or re-send the DocuSign envelope">
          <Send className="h-3.5 w-3.5" /> {s === "approved" ? "Send agreement" : "Resend"}
        </Btn>
      )}
      {(s === "signed" || s === "stripe_pending") && (
        <Btn tone={next} disabled={busy} onClick={() => onRun("resend-stripe-link")} title="Create the Stripe account if missing and re-email the payout link">
          <Send className="h-3.5 w-3.5" /> {row.stripe_account_id ? "Resend link" : "Start Stripe"}
        </Btn>
      )}
      {withRefresh && (row.docusign_envelope_id || row.stripe_account_id) && s !== "declined" && (
        <Btn disabled={busy} onClick={() => onRun("refresh")} title="Pull live DocuSign + Stripe status">
          <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
        </Btn>
      )}
    </div>
  );
}

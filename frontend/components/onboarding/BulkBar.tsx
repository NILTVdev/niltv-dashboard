import { Send } from "lucide-react";
import { BULK, type BulkAction, type BulkProgress } from "@/lib/onboarding";
import type { Application } from "@/lib/types";
import Btn from "./Btn";

export default function BulkBar({ count, agreement, stripe, confirm, progress, onAsk, onRun, onClear }: {
  count: number;
  agreement: Application[];
  stripe: Application[];
  confirm: BulkAction | null;
  progress: BulkProgress | null;
  onAsk: (a: BulkAction | null) => void;
  onRun: (a: BulkAction) => void;
  onClear: () => void;
}) {
  if (progress) {
    const running = progress.done < progress.total;
    const sent = progress.done - progress.failed.length;
    return (
      <div className="mb-3 rounded-lg border bg-white px-3 py-2 text-sm shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-semibold">
            {BULK[progress.action].label}: {running ? `sending ${progress.done + 1} of ${progress.total}` : `${sent} sent`}
            {progress.failed.length > 0 && <span className="text-red-700">, {progress.failed.length} failed</span>}
          </span>
          {!running && <Btn onClick={onClear}>Done</Btn>}
        </div>
        {progress.failed.length > 0 && (
          <ul className="mt-1 ml-4 list-disc text-xs text-red-700">
            {progress.failed.map((f) => <li key={f.name}>{f.name}: {f.error}</li>)}
          </ul>
        )}
      </div>
    );
  }
  const target = confirm === "agreement" ? agreement : stripe;
  const noStripeYet = stripe.filter((r) => !r.stripe_account_id).length;
  const plural = (n: number) => (n === 1 ? "athlete" : "athletes");
  return (
    <div className="mb-3 rounded-lg border bg-white px-3 py-2 text-sm shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold mr-1">{count} selected</span>
        <Btn disabled={agreement.length === 0} onClick={() => onAsk("agreement")}
             title="Re-send the DocuSign agreement to the selected athletes still waiting to sign">
          <Send className="h-3.5 w-3.5" /> Resend agreement ({agreement.length})
        </Btn>
        <Btn disabled={stripe.length === 0} onClick={() => onAsk("stripe")}
             title="Email the payout link to the selected athletes who signed but have not finished Stripe">
          <Send className="h-3.5 w-3.5" /> Resend Stripe link ({stripe.length})
        </Btn>
        <Btn onClick={onClear}>Clear</Btn>
      </div>
      {confirm && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
          <span>
            {confirm === "agreement"
              ? `Send the agreement again to ${target.length} ${plural(target.length)}? Each one gets a DocuSign email.`
              : `Email the payout link to ${target.length} ${plural(target.length)}?`}
            {confirm === "stripe" && noStripeYet > 0 && ` ${noStripeYet} of them have no Stripe account yet. One is created for each.`}
            {count > target.length && " Selected athletes at other steps are skipped."}
          </span>
          <Btn tone="primary" onClick={() => onRun(confirm)}>Send</Btn>
          <Btn onClick={() => onAsk(null)}>Cancel</Btn>
        </div>
      )}
    </div>
  );
}

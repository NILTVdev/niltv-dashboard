import { cn } from "@/lib/utils";
import { fmtWhen, runLine, scopeLabel } from "@/lib/onboarding";
import type { ReconcileRun } from "@/lib/types";

// Every change a run makes is a webhook that never arrived; a healthy
// pipeline shows "0 changed" here night after night.
export default function RunLog({ runs }: { runs: ReconcileRun[] }) {
  return (
    <div className="mb-5 rounded-xl border bg-white p-3 shadow-sm text-xs">
      <div className="mb-2 font-semibold text-gray-700">Refresh log</div>
      <ul className="space-y-2">
        {runs.map((run) => (
          <li key={run.id}>
            <div className={cn("text-gray-700", run.error && "text-red-700")}>
              {fmtWhen(run.started_at)} · {scopeLabel(run)} ·{" "}
              {run.finished_at ? runLine(run) : "running"}
              {run.stats?.signed_no_stripe ? ` · ${run.stats.signed_no_stripe} signed without Stripe` : ""}
              {run.error ? ` · ${run.error}` : ""}
            </div>
            {(run.stats?.changes ?? []).length > 0 && (
              <ul className="mt-1 ml-4 list-disc text-gray-500">
                {run.stats.changes!.map((c) => (
                  <li key={`${run.id}-${c.id}`}>
                    {c.name} ({c.source === "docusign" ? "DocuSign" : "Stripe"}): {c.from} → {c.to}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

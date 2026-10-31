// Helpers for the onboarding page. Moved out of OnboardingView so they can be tested.

import type { Application, ApplicationStatus, ReconcileRun } from "./types";

export const STATUS_LABEL: Record<ApplicationStatus, string> = {
  applicant: "Applicant",
  approved: "Approved",
  declined: "Declined",
  agreement_sent: "Awaiting signature",
  signed: "Signed",
  stripe_pending: "Stripe pending",
  accepted: "Accepted",
};

// Three tones, by whose move it is: amber = staff, gray = waiting on the
// athlete (or closed), green = done.
const OURS = "bg-amber-50 text-amber-800 ring-amber-200";
const WAITING = "bg-gray-100 text-gray-600 ring-gray-200";
const DONE = "bg-emerald-50 text-emerald-800 ring-emerald-200";

export const STATUS_STYLE: Record<ApplicationStatus, string> = {
  applicant: OURS,
  approved: OURS, // approved, but the agreement has not gone out
  declined: WAITING,
  agreement_sent: WAITING,
  signed: OURS, // signed, but Stripe has not been started
  stripe_pending: WAITING,
  accepted: DONE,
};

export type BulkAction = "agreement" | "stripe";
export interface BulkProgress { action: BulkAction; done: number; total: number; failed: { name: string; error: string }[] }

// Which rows each bulk action applies to; matches the backend's status checks
// in send_agreement / start_stripe.
export const BULK: Record<BulkAction, { label: string; endpoint: string; statuses: ApplicationStatus[] }> = {
  agreement: { label: "Resend agreement", endpoint: "resend-agreement", statuses: ["approved", "agreement_sent"] },
  stripe: { label: "Resend Stripe link", endpoint: "resend-stripe-link", statuses: ["signed", "stripe_pending"] },
};

// Filter tab -> what "Refresh category" re-checks (see backend reconcile.SCOPES).
export const CATEGORY_SCOPE: Record<string, string> = {
  open: "open",
  agreement_sent: "agreement_sent",
  stripe_pending: "stripe_pending",
  accepted: "accepted",
  all: "all",
};

// Filter chips in pipeline order. "open" = everything still moving.
export const FILTERS: { key: string; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "applicant", label: "Applicants" },
  { key: "agreement_sent", label: "Awaiting signature" },
  { key: "stripe_pending", label: "Stripe pending" },
  { key: "accepted", label: "Accepted" },
  { key: "declined", label: "Declined" },
  { key: "all", label: "All" },
];

export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// How long something has been waiting, in whole days.
export function ago(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

// The line under the status pill: what the row is waiting on, so staff don't
// have to open it. alert = it stays stuck until staff do something.
export function waitingOn(r: Application): { text: string; alert?: boolean } | null {
  switch (r.status) {
    case "applicant":
      return r.missing_for_approval.length
        ? { text: `Missing ${r.missing_for_approval.join(", ")}`, alert: true }
        : { text: "Ready for review" };
    case "approved":
      return { text: "Agreement not sent", alert: true };
    case "agreement_sent":
      if (!r.agreement_sent_at) return null;
      return { text: `Sent ${ago(r.agreement_sent_at)}${r.agreement_reminded_at ? `, reminded ${ago(r.agreement_reminded_at)}` : ""}` };
    case "signed":
      return { text: "Stripe not started", alert: true };
    case "stripe_pending": {
      const sent = r.stripe_link_sent_at ? `link sent ${ago(r.stripe_link_sent_at)}` : null;
      // The checklist detail already has Stripe's requirement codes in words.
      const needs = r.stripe_requirements_due?.length ? r.progress.find((s) => s.key === "stripe")?.detail : null;
      if (needs) return { text: [needs, sent].filter(Boolean).join(" · ") };
      if (!r.stripe_payouts_enabled && sent) return { text: `Not started, ${sent}` };
      return null;
    }
    case "declined":
      return r.decline_reason ? { text: r.decline_reason } : null;
    default:
      return null;
  }
}

export function countBy(values: (string | null | undefined)[]): [string, number][] {
  const m = new Map<string, number>();
  for (const v of values) if (v) m.set(v, (m.get(v) ?? 0) + 1);
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function scopeLabel(run: ReconcileRun): string {
  if (run.trigger === "nightly") return "Nightly";
  const scope = run.stats?.scope ?? "all";
  if (scope === "all") return "Refresh all";
  return `Refresh ${FILTERS.find((f) => f.key === scope)?.label ?? scope}`;
}

export function runLine(run: ReconcileRun): string {
  const s = run.stats ?? {};
  const checked = (s.docusign_checked ?? 0) + (s.stripe_checked ?? 0);
  const parts = [`${checked} checked`, `${s.changed ?? 0} changed`];
  if (s.errors || run.error) parts.push(`${s.errors ?? 0} errors`);
  return parts.join(", ");
}

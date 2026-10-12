"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check, Circle, CircleDashed, Ban, MinusCircle, RefreshCw, Send, ChevronDown, ChevronUp,
  ExternalLink, Search,
} from "lucide-react";
import { cn, fmtDate } from "@/lib/utils";
import type {
  Application, ApplicationEvent, ApplicationStatus, ApplicationStep, ApplicationsSummary, ReconcileRun,
} from "@/lib/types";

interface Props {
  initial: Application[];
  summary: ApplicationsSummary | null;
}

// The Needs column names what the row is waiting on, not the step it is on.
const NEEDS_LABEL: Record<string, string> = {
  reviewed: "Approval",
  agreement: "Agreement",
  stripe: "Stripe payouts",
};

const STATUS_LABEL: Record<ApplicationStatus, string> = {
  applicant: "Applicant",
  approved: "Approved",
  declined: "Declined",
  agreement_sent: "Agreement sent",
  signed: "Signed",
  stripe_pending: "Stripe pending",
  accepted: "Accepted",
};

const STATUS_STYLE: Record<ApplicationStatus, string> = {
  applicant: "bg-amber-50 text-amber-800 ring-amber-200",
  approved: "bg-sky-50 text-sky-800 ring-sky-200",
  declined: "bg-gray-100 text-gray-600 ring-gray-200",
  agreement_sent: "bg-sky-50 text-sky-800 ring-sky-200",
  signed: "bg-indigo-50 text-indigo-800 ring-indigo-200",
  stripe_pending: "bg-violet-50 text-violet-800 ring-violet-200",
  accepted: "bg-emerald-50 text-emerald-800 ring-emerald-200",
};

type BulkAction = "agreement" | "stripe";
interface BulkProgress { action: BulkAction; done: number; total: number; failed: { name: string; error: string }[] }

// Which rows each bulk action applies to; matches the backend's status checks
// in send_agreement / start_stripe.
const BULK: Record<BulkAction, { label: string; endpoint: string; statuses: ApplicationStatus[] }> = {
  agreement: { label: "Resend agreement", endpoint: "resend-agreement", statuses: ["approved", "agreement_sent"] },
  stripe: { label: "Resend Stripe link", endpoint: "resend-stripe-link", statuses: ["signed", "stripe_pending"] },
};

// Filter tab -> what "Refresh category" re-checks (see backend reconcile.SCOPES).
const CATEGORY_SCOPE: Record<string, string> = {
  open: "open",
  agreement_sent: "agreement_sent",
  stripe_pending: "stripe_pending",
  accepted: "accepted",
  all: "all",
};

// Filter chips in pipeline order. "open" = everything still moving.
const FILTERS: { key: string; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "applicant", label: "Applicants" },
  { key: "agreement_sent", label: "Awaiting signature" },
  { key: "stripe_pending", label: "Stripe pending" },
  { key: "accepted", label: "Accepted" },
  { key: "declined", label: "Declined" },
  { key: "all", label: "All" },
];

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// Bulk sends report a provider failure in the body ("error") with a 200, so
// they read the whole response instead of going through act().
async function bulkAct(id: number, endpoint: string): Promise<Application> {
  const res = await fetch(`/api/proxy/api/applications/${id}/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? `HTTP ${res.status}`);
  if (data.error) throw new Error(String(data.error));
  return data.application as Application;
}

async function act(id: number, action: string, body?: unknown): Promise<Application> {
  const res = await fetch(`/api/proxy/api/applications/${id}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? `HTTP ${res.status}`);
  // approve/decline/update return the row; resend/refresh wrap it.
  return (data.application ?? data) as Application;
}

export default function OnboardingView({ initial, summary }: Props) {
  const [rows, setRows] = useState<Application[]>(initial);
  const [filter, setFilter] = useState<string>("open");
  const [school, setSchool] = useState("all");
  const [sport, setSport] = useState("all");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmBulk, setConfirmBulk] = useState<BulkAction | null>(null);
  const [bulk, setBulk] = useState<BulkProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runs, setRuns] = useState<ReconcileRun[]>([]);
  const [showRuns, setShowRuns] = useState(false);

  // Staff notification emails link to ?id=<n>; open that row on arrival.
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("id"));
    if (id) {
      setOpenId(id);
      setFilter("all");
    }
  }, []);

  // Counts per school / sport over the rows the status filter leaves in, so the
  // dropdowns read "Duke University (60)" and the labels "Schools (12)".
  const statusRows = useMemo(
    () => rows.filter((r) => {
      if (filter === "open") return r.status !== "declined" && r.status !== "accepted";
      if (filter === "all") return true;
      return r.status === filter;
    }),
    [rows, filter],
  );
  const schools = useMemo(() => countBy(statusRows.map((r) => r.university)), [statusRows]);
  const sports = useMemo(() => countBy(statusRows.map((r) => r.sport)), [statusRows]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length, open: 0 };
    for (const r of rows) {
      c[r.status] = (c[r.status] ?? 0) + 1;
      if (r.status !== "declined" && r.status !== "accepted") c.open += 1;
    }
    return c;
  }, [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase().replace(/^@/, "");
    return rows.filter((r) => {
      if (filter === "open" && (r.status === "declined" || r.status === "accepted")) return false;
      if (filter !== "open" && filter !== "all" && r.status !== filter) return false;
      if (school !== "all" && r.university !== school) return false;
      if (sport !== "all" && r.sport !== sport) return false;
      if (q) {
        const hay = `${r.first_name ?? ""} ${r.last_name ?? ""} ${r.email} ${r.instagram ?? ""} ${r.university ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, filter, school, sport, search]);

  function replace(updated: Application) {
    setRows((prev) => prev.map((r) => (r.id === updated.id ? { ...r, ...updated } : r)));
  }

  async function run(id: number, action: string, body?: unknown) {
    setBusy(id);
    setError(null);
    try {
      replace(await act(id, action, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  // "Refresh all" = the nightly reconcile, on demand. It runs in the
  // background on the API; poll the run list until it finishes, then reload
  // the rows it may have moved.
  async function loadRuns(): Promise<ReconcileRun[]> {
    const res = await fetch("/api/proxy/api/applications/reconcile/runs?limit=10");
    const data = res.ok ? ((await res.json()) as ReconcileRun[]) : [];
    setRuns(data);
    return data;
  }

  useEffect(() => {
    loadRuns().catch(() => {});
  }, []);

  const lastRun = runs[0];
  // A run unfinished after 15 minutes died with the process (same rule as the API).
  const refreshing = !!lastRun && !lastRun.finished_at
    && Date.now() - new Date(lastRun.started_at).getTime() < 15 * 60_000;

  // Filter tab -> reconcile scope. Applicants and declined rows have nothing
  // waiting on DocuSign or Stripe.
  const categoryScope = CATEGORY_SCOPE[filter] ?? null;

  async function refreshRows(scope: string) {
    setError(null);
    try {
      const res = await fetch(`/api/proxy/api/applications/reconcile?scope=${encodeURIComponent(scope)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? `HTTP ${res.status}`);
      setRuns((prev) => [data as ReconcileRun, ...prev]);
      for (let i = 0; i < 300; i++) { // 15 minutes, the API's stale-run limit
        await new Promise((r) => setTimeout(r, 3000));
        const latest = (await loadRuns()).find((r) => r.id === data.id);
        if (!latest || latest.finished_at) break;
      }
      const list = await fetch("/api/proxy/api/applications/?status=all&limit=2000");
      if (list.ok) setRows((await list.json()) as Application[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      loadRuns().catch(() => {});
    }
  }

  // Multi-select: a new status tab starts a new selection, so nothing hidden
  // by the tab is ever sent by mistake.
  useEffect(() => {
    setSelected(new Set());
    setConfirmBulk(null);
  }, [filter]);

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const bulkRunning = !!bulk && bulk.done < bulk.total;
  const allVisibleSelected = filtered.length > 0 && filtered.every((r) => selected.has(r.id));
  function toggleAllVisible() {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const r of filtered) {
        if (allVisibleSelected) next.delete(r.id);
        else next.add(r.id);
      }
      return next;
    });
  }

  const selectedRows = rows.filter((r) => selected.has(r.id));
  const eligible = (action: BulkAction) => selectedRows.filter((r) => BULK[action].statuses.includes(r.status));

  // One request per athlete through the same endpoints as the row buttons,
  // so every send lands in that athlete's timeline. Sequential on purpose:
  // DocuSign and Stripe both rate-limit bursts.
  async function runBulk(action: BulkAction) {
    const targets = eligible(action);
    setConfirmBulk(null);
    setError(null);
    setBulk({ action, done: 0, total: targets.length, failed: [] });
    const failed: { name: string; error: string }[] = [];
    for (let i = 0; i < targets.length; i++) {
      const r = targets[i];
      try {
        replace(await bulkAct(r.id, BULK[action].endpoint));
      } catch (e) {
        failed.push({
          name: `${r.first_name ?? ""} ${r.last_name ?? ""}`.trim() || r.email,
          error: e instanceof Error ? e.message : String(e),
        });
      }
      setBulk({ action, done: i + 1, total: targets.length, failed: [...failed] });
    }
    setSelected(new Set());
  }

  async function toggle(id: number) {
    if (openId === id) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    const row = rows.find((r) => r.id === id);
    if (row && !row.events) {
      try {
        const res = await fetch(`/api/proxy/api/applications/${id}`);
        if (res.ok) replace((await res.json()) as Application);
      } catch {
        /* detail stays collapsed to the list fields */
      }
    }
  }

  const integ = summary?.integrations;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4 mb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Athlete Onboarding</h1>
          <p className="text-sm text-gray-500 mt-1">
            Apply → approve → agreement → Stripe → accepted. Approve sends the DocuSign agreement;
            the signed envelope triggers the Stripe payout link automatically.
          </p>
        </div>
        {integ && (
          <div className="flex flex-wrap gap-2 text-xs">
            <Integration ok={integ.docusign || integ.docusign_powerform} label={integ.docusign ? "DocuSign API" : "DocuSign PowerForm"} />
            <Integration ok={integ.stripe} label="Stripe" />
            <Integration ok={integ.payout_links} label="Payout links" />
            <Integration ok={integ.email} label="Email" />
          </div>
        )}
      </div>

      {/* Pipeline counts */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-5">
        {(["applicant", "agreement_sent", "signed", "stripe_pending", "accepted", "declined"] as ApplicationStatus[]).map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s === "signed" ? "all" : s)}
            className={cn(
              "rounded-xl border bg-white p-3 text-left shadow-sm hover:border-[var(--brand-light)] transition-colors",
              filter === s && "ring-2 ring-[var(--brand-light)]",
            )}
          >
            <div className="text-2xl font-bold text-[var(--brand)]">{counts[s] ?? 0}</div>
            <div className="text-xs text-gray-500">{STATUS_LABEL[s]}</div>
          </button>
        ))}
      </div>

      {/* Filters: status tabs on their own row; school/sport + search on the
          next. One wrapping row used to strand the search box on a second
          line, right-aligned by ml-auto, at tablet widths. */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
      <div className="flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1 w-fit max-w-full">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "h-7 px-3 rounded-md text-xs font-semibold transition-colors",
              filter === f.key ? "bg-white text-[var(--brand)] shadow-sm" : "text-gray-600 hover:text-gray-900",
            )}
          >
            {f.label}
            <span className="ml-1 text-gray-400">{counts[f.key] ?? 0}</span>
          </button>
        ))}
      </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <Btn
            disabled={refreshing || !categoryScope}
            onClick={() => categoryScope && refreshRows(categoryScope)}
            title={categoryScope
              ? `Re-check the ${FILTERS.find((f) => f.key === filter)?.label ?? ""} tab against DocuSign and Stripe`
              : "Nothing in this tab is waiting on DocuSign or Stripe"}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} /> Refresh category
          </Btn>
          <Btn disabled={refreshing} onClick={() => refreshRows("all")}
               title="Re-check every row against DocuSign and Stripe (also runs nightly)">
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} /> Refresh all
          </Btn>
        </div>
      </div>
      {lastRun && (
        <div className="mb-2 text-right">
          <button onClick={() => setShowRuns((v) => !v)} className="text-xs text-gray-500 hover:text-gray-800 underline-offset-2 hover:underline">
            {refreshing
              ? "Refreshing…"
              : `Last refresh ${fmtWhen(lastRun.finished_at)} · ${scopeLabel(lastRun)}: ${runLine(lastRun)}`}
          </button>
        </div>
      )}
      {showRuns && runs.length > 0 && <RunLog runs={runs} />}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={school} onChange={(e) => setSchool(e.target.value)} className="h-9 rounded-md border px-2 text-sm bg-white">
          <option value="all">Schools ({schools.length})</option>
          {schools.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
        </select>
        <select value={sport} onChange={(e) => setSport(e.target.value)} className="h-9 rounded-md border px-2 text-sm bg-white">
          <option value="all">Sports ({sports.length})</option>
          {sports.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
        </select>
        {/* Grows into whatever is left of the row (capped), instead of a fixed
            box that either fits or wraps; on a narrow screen it takes the
            full width of its own row. */}
        <label className="relative flex-1 min-w-[12rem] sm:max-w-xs sm:ml-auto">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name, email, @handle"
            className="h-9 w-full rounded-md border pl-8 pr-3 text-sm bg-white"
          />
        </label>
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}

      {(selected.size > 0 || bulk) && (
        <BulkBar
          count={selected.size}
          agreement={eligible("agreement")}
          stripe={eligible("stripe")}
          confirm={confirmBulk}
          progress={bulk}
          onAsk={setConfirmBulk}
          onRun={runBulk}
          onClear={() => {
            setSelected(new Set());
            setConfirmBulk(null);
            setBulk(null);
          }}
        />
      )}

      <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="pl-3 py-2 w-6">
                <input type="checkbox" aria-label="Select all shown" checked={allVisibleSelected}
                       onChange={toggleAllVisible} disabled={filtered.length === 0 || bulkRunning} />
              </th>
              <th className="px-3 py-2 w-8" />
              <th className="px-3 py-2">Athlete</th>
              <th className="px-3 py-2">School / Sport</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Progress</th>
              <th className="px-3 py-2">Needs</th>
              <th className="px-3 py-2">Applied</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-10 text-center text-gray-400">
                  {rows.length === 0 ? "No applications yet. The signup form on niltv.com posts here." : "Nothing matches these filters."}
                </td>
              </tr>
            )}
            {filtered.map((r) => {
              const open = openId === r.id;
              const need = r.progress.find((s) => s.state === "current" || s.state === "blocked");
              return (
                <RowGroup key={r.id} open={open}>
                  <tr className={cn("hover:bg-gray-50 cursor-pointer", open && "bg-[var(--brand-pale)]/40")} onClick={() => toggle(r.id)}>
                    <td className="pl-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Select ${r.first_name ?? ""} ${r.last_name ?? ""}`}
                             checked={selected.has(r.id)} onChange={() => toggleSelected(r.id)} disabled={bulkRunning} />
                    </td>
                    <td className="px-3 py-2 text-gray-400">{open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}</td>
                    <td className="px-3 py-2">
                      <div className="font-medium">{r.first_name} {r.last_name}</div>
                      <div className="text-xs text-gray-500">
                        {r.instagram ? `@${r.instagram}` : r.email}
                        {r.international && <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600" title="International student (from the form)">INTL</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div>{r.university ?? <span className="text-gray-400">?</span>}</div>
                      <div className="text-xs text-gray-500">{[r.sport, r.year].filter(Boolean).join(" · ")}</div>
                    </td>
                    <td className="px-3 py-2">
                      <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1", STATUS_STYLE[r.status])}>
                        {STATUS_LABEL[r.status]}
                      </span>
                    </td>
                    <td className="px-3 py-2"><Progress steps={r.progress} /></td>
                    <td className="px-3 py-2 text-xs text-gray-600 max-w-[16rem]">
                      {r.status === "accepted" ? <span className="text-emerald-700">Complete</span>
                        : need ? <span>{NEEDS_LABEL[need.key] ?? need.label}{need.detail ? `: ${need.detail}` : ""}</span> : null}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{fmtDate(r.created_at)}</td>
                    <td className="px-3 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                      <Actions row={r} busy={busy === r.id} onRun={(a, b) => run(r.id, a, b)} />
                    </td>
                  </tr>
                  {open && (
                    <tr className="bg-[var(--brand-pale)]/30">
                      <td colSpan={9} className="px-6 py-4">
                        <Detail row={r} busy={busy === r.id} onRun={(a, b) => run(r.id, a, b)} />
                      </td>
                    </tr>
                  )}
                </RowGroup>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RowGroup({ children }: { open: boolean; children: React.ReactNode }) {
  return <>{children}</>;
}

function BulkBar({ count, agreement, stripe, confirm, progress, onAsk, onRun, onClear }: {
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

function scopeLabel(run: ReconcileRun): string {
  if (run.trigger === "nightly") return "Nightly";
  const scope = run.stats?.scope ?? "all";
  if (scope === "all") return "Refresh all";
  return `Refresh ${FILTERS.find((f) => f.key === scope)?.label ?? scope}`;
}

function runLine(run: ReconcileRun): string {
  const s = run.stats ?? {};
  const checked = (s.docusign_checked ?? 0) + (s.stripe_checked ?? 0);
  const parts = [`${checked} checked`, `${s.changed ?? 0} changed`];
  if (s.errors || run.error) parts.push(`${s.errors ?? 0} errors`);
  return parts.join(", ");
}

// Every change a run makes is a webhook that never arrived; a healthy
// pipeline shows "0 changed" here night after night.
function RunLog({ runs }: { runs: ReconcileRun[] }) {
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

function Integration({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1",
      ok ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200")}>
      <span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-emerald-500" : "bg-amber-500")} />
      {label}{ok ? "" : " not configured"}
    </span>
  );
}

function StepIcon({ state }: { state: ApplicationStep["state"] }) {
  const cls = "h-4 w-4";
  switch (state) {
    case "done": return <Check className={cn(cls, "text-emerald-600")} />;
    case "current": return <CircleDashed className={cn(cls, "text-[var(--brand-light)]")} />;
    case "blocked": return <Ban className={cn(cls, "text-red-500")} />;
    case "skipped": return <MinusCircle className={cn(cls, "text-gray-400")} />;
    default: return <Circle className={cn(cls, "text-gray-300")} />;
  }
}

function Progress({ steps }: { steps: ApplicationStep[] }) {
  return (
    <div className="flex items-center gap-1" title={steps.map((s) => `${s.label}: ${s.state}${s.detail ? ` (${s.detail})` : ""}`).join("\n")}>
      {steps.map((s, i) => (
        <div key={s.key} className="flex items-center">
          <StepIcon state={s.state} />
          {i < steps.length - 1 && <span className={cn("mx-0.5 h-px w-3", s.state === "done" ? "bg-emerald-400" : "bg-gray-200")} />}
        </div>
      ))}
    </div>
  );
}

function Btn({ children, onClick, disabled, tone = "default", title }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean; tone?: "default" | "primary" | "danger"; title?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition-colors disabled:opacity-50",
        tone === "primary" && "bg-[var(--brand)] text-white hover:opacity-90",
        tone === "danger" && "border border-red-200 text-red-700 hover:bg-red-50",
        tone === "default" && "border text-gray-700 hover:bg-gray-50",
      )}
    >
      {children}
    </button>
  );
}

function Actions({ row, busy, onRun }: { row: Application; busy: boolean; onRun: (a: string, b?: unknown) => void }) {
  const s = row.status;
  const decline = () => {
    const reason = window.prompt("Decline reason (kept on the record; optional):", row.decline_reason ?? "");
    if (reason === null) return;
    const notify = window.confirm("Email the athlete that they were not selected?");
    onRun("decline", { reason, notify });
  };
  return (
    <div className="flex flex-wrap justify-end gap-1">
      {(s === "applicant" || s === "declined") && (
        <Btn tone="primary" disabled={busy || row.missing_for_approval.length > 0}
             title={row.missing_for_approval.length ? `Missing: ${row.missing_for_approval.join(", ")}` : "Approve and send the agreement"}
             onClick={() => onRun("approve", { by: "staff" })}>
          <Check className="h-3.5 w-3.5" /> Approve
        </Btn>
      )}
      {(s === "applicant" || s === "approved" || s === "agreement_sent") && (
        <Btn tone="danger" disabled={busy} onClick={decline}><Ban className="h-3.5 w-3.5" /> Decline</Btn>
      )}
      {(s === "approved" || s === "agreement_sent") && (
        <Btn disabled={busy} onClick={() => onRun("resend-agreement")} title="Create or re-send the DocuSign envelope">
          <Send className="h-3.5 w-3.5" /> {s === "approved" ? "Send agreement" : "Resend"}
        </Btn>
      )}
      {(s === "signed" || s === "stripe_pending") && (
        <Btn disabled={busy} onClick={() => onRun("resend-stripe-link")} title="Create the Stripe account if missing and re-email the payout link">
          <Send className="h-3.5 w-3.5" /> {row.stripe_account_id ? "Resend link" : "Start Stripe"}
        </Btn>
      )}
      {(row.docusign_envelope_id || row.stripe_account_id) && s !== "declined" && (
        <Btn disabled={busy} onClick={() => onRun("refresh")} title="Pull live DocuSign + Stripe status">
          <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
        </Btn>
      )}
    </div>
  );
}

function Detail({ row, busy, onRun }: { row: Application; busy: boolean; onRun: (a: string, b?: unknown) => void }) {
  // Draft starts from the saved notes; after Save the row comes back with the
  // same text, so no sync effect is needed.
  const [notes, setNotes] = useState(row.notes ?? "");
  const [more, setMore] = useState(false);
  const answers = row.answers ?? {};
  const consents: [string, boolean][] = [
    ["18+ confirmed", row.confirm_age],
    ["Terms + Privacy", row.consent_terms],
  ];
  const missing = new Set(row.missing_for_approval);
  const socials = [
    row.instagram && { label: `@${row.instagram}`, href: `https://instagram.com/${row.instagram}`, n: row.instagram_followers, site: "Instagram" },
    row.tiktok && { label: `@${row.tiktok}`, href: `https://www.tiktok.com/@${row.tiktok}`, n: row.tiktok_followers, site: "TikTok" },
    row.youtube && { label: row.youtube.replace(/^https?:\/\/(www\.)?/, ""), href: /^https?:/.test(row.youtube) ? row.youtube : `https://youtube.com/${row.youtube}`, n: row.youtube_subscribers, site: "YouTube" },
  ].filter(Boolean) as { label: string; href: string; n: string | null; site: string }[];

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      {/* Steps */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Checklist</h3>
        <ol className="space-y-2">
          {row.progress.map((s) => (
            <li key={s.key} className="flex items-start gap-2">
              <span className="mt-0.5"><StepIcon state={s.state} /></span>
              <div>
                <div className={cn("text-sm font-medium", s.state === "todo" && "text-gray-400")}>{s.label}</div>
                {(s.detail || s.at) && (
                  <div className="text-xs text-gray-500">{[s.detail, fmtWhen(s.at)].filter(Boolean).join(" · ")}</div>
                )}
              </div>
            </li>
          ))}
        </ol>
        <div className="mt-4 space-y-1 text-xs text-gray-600">
          {row.docusign_envelope_id && (
            <div>
              Envelope <code className="text-[11px]">{row.docusign_envelope_id}</code> ({row.docusign_status})
              {row.agreement_sent_at && <> · sent {fmtWhen(row.agreement_sent_at)}</>}
              {row.agreement_reminded_at && <> · last reminded {fmtWhen(row.agreement_reminded_at)}</>}
            </div>
          )}
          {row.stripe_account_id && (
            <div className="flex items-center gap-1">
              <a className="text-[var(--brand)] hover:underline inline-flex items-center gap-1"
                 href={`https://dashboard.stripe.com/connect/accounts/${row.stripe_account_id}`} target="_blank" rel="noreferrer">
                {row.stripe_account_id} <ExternalLink className="h-3 w-3" />
              </a>
              {row.stripe_payouts_enabled ? <span className="text-emerald-700">payouts enabled</span> : <span className="text-amber-700">payouts off</span>}
            </div>
          )}
          {row.stripe_requirements_due && row.stripe_requirements_due.length > 0 && (
            <div>Stripe still needs: {row.stripe_requirements_due.join(", ")}</div>
          )}
          {row.payout_link && (
            <div className="truncate">Payout link: <a className="text-[var(--brand)] hover:underline" href={row.payout_link} target="_blank" rel="noreferrer">{row.payout_link}</a></div>
          )}
          {row.decline_reason && <div className="text-red-700">Declined: {row.decline_reason}</div>}
        </div>
        <div className="mt-4 flex flex-wrap gap-1">
          <Actions row={row} busy={busy} onRun={onRun} />
        </div>
        {row.missing_for_approval.length > 0 && (
          <div className="mt-2 text-xs text-amber-700">Before approval: {row.missing_for_approval.join(", ")}</div>
        )}
      </section>

      {/* Application: the four things approval needs, then everything else behind View more */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Application</h3>
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5 text-sm">
          <Dt>Name</Dt><Dd><Need ok={!missing.has("name")}>{[row.first_name, row.last_name].filter(Boolean).join(" ")}</Need></Dd>
          <Dt>Email</Dt><Dd><Need ok={!missing.has("email")}><a className="hover:underline" href={`mailto:${row.email}`}>{row.email}</a></Need></Dd>
          <Dt>Roster</Dt><Dd><Need ok={!missing.has("roster link")}>{row.roster_link && <a className="text-[var(--brand)] hover:underline break-all" href={row.roster_link} target="_blank" rel="noreferrer">{row.roster_link.replace(/^https?:\/\/(www\.)?/, "")}</a>}</Need></Dd>
          <Dt>Socials</Dt><Dd><Need ok={!missing.has("a social link")}>
            <span className="flex flex-wrap gap-x-3 gap-y-0.5">
              {socials.map((x) => (
                <span key={x.site}><a className="text-[var(--brand)] hover:underline" href={x.href} target="_blank" rel="noreferrer">{x.label}</a>{x.n && <span className="text-gray-500"> {x.n}</span>}</span>
              ))}
            </span>
          </Need></Dd>
          <Dt>School</Dt><Dd>{[row.university, row.sport, row.year].filter(Boolean).join(" · ")}{row.campus_channel_label && row.campus_channel !== "other" ? <span className="text-gray-500"> · {row.campus_channel_label}</span> : ""}</Dd>
        </dl>
        <button type="button" onClick={() => setMore(!more)} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-[var(--brand)] hover:underline">
          {more ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />} {more ? "Less" : "View more"}
        </button>
        {more && (
          <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-sm border-t pt-2">
            <Dt>Phone</Dt><Dd>{row.phone}</Dd>
            <Dt>College email</Dt><Dd>{row.college_email}</Dd>
            <Dt>International</Dt><Dd>{row.international === true ? "yes" : row.international === false ? "no" : ""}</Dd>
            <Dt>NIL deals</Dt><Dd>{[row.nil_deals_done && `done: ${row.nil_deals_done}`, row.nil_deals_wanted && `wants: ${row.nil_deals_wanted}`].filter(Boolean).join(" · ")}</Dd>
            <Dt>Purpose</Dt><Dd className="whitespace-pre-wrap">{row.purpose}</Dd>
            <Dt>Content</Dt><Dd className="whitespace-pre-wrap">{row.content_type}</Dd>
            <Dt>Other followers</Dt><Dd>{row.other_followers}</Dd>
            <Dt>About</Dt><Dd className="whitespace-pre-wrap">{row.description}</Dd>
            <Dt>Source</Dt><Dd>{row.source}{row.submit_count > 1 ? ` · submitted ${row.submit_count}×` : ""}{typeof answers.universityAsTyped === "string" && answers.universityAsTyped !== row.university ? ` · school typed as "${answers.universityAsTyped}"` : ""}</Dd>
          </dl>
        )}
        <div className="mt-3 flex flex-wrap gap-1">
          {consents.map(([label, ok]) => (
            <span key={label} className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
              ok ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-gray-50 text-gray-500 ring-gray-200 line-through")}>
              {label}
            </span>
          ))}
          {row.consent_version && <span className="text-[11px] text-gray-400 self-center ml-1">v{row.consent_version} · {fmtDate(row.consent_at)}</span>}
        </div>
        {more && Object.keys(answers).length > 0 && (
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-gray-500">Raw answers</summary>
            <pre className="mt-1 max-h-64 overflow-auto rounded bg-white p-2 text-[11px]">{JSON.stringify(answers, null, 2)}</pre>
          </details>
        )}
      </section>

      {/* Notes + timeline */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Notes</h3>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="w-full rounded-md border bg-white px-2 py-1.5 text-sm"
          placeholder="Internal notes (never shown to the athlete)"
        />
        <div className="mt-1 text-right">
          <Btn disabled={busy || notes === (row.notes ?? "")} onClick={() => onRun("update", { notes })}>Save notes</Btn>
        </div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mt-4 mb-2">Timeline</h3>
        {row.events ? (
          <ol className="space-y-1.5 text-xs max-h-72 overflow-auto pr-1">
            {[...row.events].reverse().map((e, i) => <EventLine key={i} e={e} />)}
          </ol>
        ) : (
          <div className="text-xs text-gray-400">Loading…</div>
        )}
      </section>
    </div>
  );
}

function countBy(values: (string | null | undefined)[]): [string, number][] {
  const m = new Map<string, number>();
  for (const v of values) if (v) m.set(v, (m.get(v) ?? 0) + 1);
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function Need({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-start gap-1">
      {ok ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" /> : <MinusCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />}
      <span>{children || <span className="text-amber-700">missing</span>}</span>
    </span>
  );
}

function Dt({ children }: { children: React.ReactNode }) {
  return <dt className="text-gray-500">{children}</dt>;
}
function Dd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <dd className={cn("text-gray-900 min-h-[1.25rem]", className)}>{children}</dd>;
}

function EventLine({ e }: { e: ApplicationEvent }) {
  const isErr = e.kind === "error";
  const d = e.detail ?? {};
  const bits: string[] = [];
  if (typeof d.by === "string") bits.push(`by ${d.by}`);
  if (typeof d.reason === "string" && d.reason) bits.push(d.reason);
  if (typeof d.mode === "string") bits.push(d.mode);
  if (typeof d.error === "string") bits.push(d.error);
  if (Array.isArray(d.currently_due) && d.currently_due.length) bits.push(`due: ${(d.currently_due as string[]).join(", ")}`);
  if (d.payouts_enabled === true) bits.push("payouts enabled");
  return (
    <li className={cn("flex gap-2", isErr && "text-red-700")}>
      <span className="text-gray-400 whitespace-nowrap w-28 shrink-0">{fmtWhen(e.at)}</span>
      <span>
        <span className="font-medium">{e.kind.replace(/_/g, " ")}</span>
        {e.actor && <span className="text-gray-400"> · {e.actor}</span>}
        {bits.length > 0 && <span className="text-gray-600"> — {bits.join(" · ")}</span>}
      </span>
    </li>
  );
}

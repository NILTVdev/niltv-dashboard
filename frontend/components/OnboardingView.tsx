"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Application, ApplicationsSummary, ReconcileRun } from "@/lib/types";
import {
  BULK, CATEGORY_SCOPE, FILTERS, countBy, fmtWhen, runLine, scopeLabel,
  type BulkAction, type BulkProgress,
} from "@/lib/onboarding";
import ApplicationRow from "@/components/onboarding/ApplicationRow";
import Btn from "@/components/onboarding/Btn";
import BulkBar from "@/components/onboarding/BulkBar";
import RunLog from "@/components/onboarding/RunLog";

interface Props {
  initial: Application[];
  summary: ApplicationsSummary | null;
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

  // Multi-select: changing the tab, school, sport or search starts a new
  // selection, so a row hidden by the current view is never sent by mistake.
  useEffect(() => {
    setSelected(new Set());
    setConfirmBulk(null);
  }, [filter, school, sport, search]);

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
            <Integration ok={integ.docusign || integ.docusign_powerform} label="DocuSign" />
            <Integration ok={integ.stripe} label="Stripe" />
            <Integration ok={integ.payout_links} label="Payout links" />
            <Integration ok={integ.email} label="Email" />
          </div>
        )}
      </div>

      {/* Filters: status tabs on their own row; school/sport + search on the
          next. One wrapping row used to strand the search box on a second
          line, right-aligned by ml-auto, at tablet widths. */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
      {/* On a phone the tabs stay on one line and swipe sideways. */}
      <div className="flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1 w-fit max-w-full max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:[scrollbar-width:none] max-sm:[&::-webkit-scrollbar]:hidden">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "h-7 shrink-0 whitespace-nowrap px-3 rounded-md text-xs font-semibold transition-colors",
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
        <select value={school} onChange={(e) => setSchool(e.target.value)} className="h-9 rounded-md border px-2 text-sm bg-white max-sm:min-w-0 max-sm:flex-1">
          <option value="all">Schools ({schools.length})</option>
          {schools.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
        </select>
        <select value={sport} onChange={(e) => setSport(e.target.value)} className="h-9 rounded-md border px-2 text-sm bg-white max-sm:min-w-0 max-sm:flex-1">
          <option value="all">Sports ({sports.length})</option>
          {sports.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
        </select>
        {/* Grows into whatever is left of the row (capped), instead of a fixed
            box that either fits or wraps; on a narrow screen it takes the
            full width of its own row. */}
        <label className="relative flex-1 min-w-[12rem] sm:max-w-xs sm:ml-auto max-sm:basis-full">
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

      {/* On a phone (below sm) the table turns into stacked rows: the header
          keeps only Select all, and each row is a small grid with the
          checkbox and chevron beside name, school, status and actions. */}
      <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
        <table className="w-full text-sm max-sm:block">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500 max-sm:block">
            <tr className="max-sm:flex max-sm:items-center">
              <th className="pl-3 py-2 w-6 max-sm:w-auto">
                <label className="flex items-center gap-2">
                  <input type="checkbox" aria-label="Select all shown" checked={allVisibleSelected}
                         onChange={toggleAllVisible} disabled={filtered.length === 0 || bulkRunning} />
                  <span className="sm:hidden">Select all</span>
                </label>
              </th>
              <th className="px-3 py-2 w-8 max-sm:hidden" />
              <th className="px-3 py-2 max-sm:hidden">Athlete</th>
              <th className="px-3 py-2 max-sm:hidden">School / Sport</th>
              <th className="px-3 py-2 max-sm:hidden">Status</th>
              {/* Progress and Applied are the first to go below desktop width;
                  the status line already says where the row is. */}
              <th className="hidden px-3 py-2 lg:table-cell">Progress</th>
              <th className="hidden px-3 py-2 lg:table-cell">Applied</th>
              <th className="px-3 py-2 text-right max-sm:hidden">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y max-sm:block">
            {filtered.length === 0 && (
              <tr className="max-sm:block">
                <td colSpan={8} className="px-3 py-10 text-center text-gray-400 max-sm:block">
                  {rows.length === 0 ? "No applications yet. The signup form on niltv.com posts here." : "Nothing matches these filters."}
                </td>
              </tr>
            )}
            {filtered.map((r) => (
              <ApplicationRow
                key={r.id}
                row={r}
                open={openId === r.id}
                selected={selected.has(r.id)}
                selectDisabled={bulkRunning}
                busy={busy === r.id}
                onToggle={() => toggle(r.id)}
                onSelect={() => toggleSelected(r.id)}
                onRun={(action, body) => run(r.id, action, body)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Shown only when something is not set up; a configured integration says nothing.
function Integration({ ok, label }: { ok: boolean; label: string }) {
  if (ok) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 bg-amber-50 text-amber-800 ring-amber-200">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      {label} not configured
    </span>
  );
}


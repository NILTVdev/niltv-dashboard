"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Download, Search, X } from "lucide-react";
import { cn, fmt } from "@/lib/utils";
import {
  DIRECTORY_PATH, EMPTY_FILTERS, FOLLOWER_RANGES, PAGE_SIZE, SORT_LABEL, STATUS_LABEL,
  activeFilterCount, filtersToApiQuery, filtersToPageQuery, followerLabel, personPath, resultRange,
  type DirectoryFilters,
} from "@/lib/athleteDirectory";
import type { DirectoryFacets, DirectoryPage, DirectoryPerson, DirectorySort, DirectoryStatus } from "@/lib/types";
import AthleteAvatar from "./AthleteAvatar";

interface Props {
  initialFilters: DirectoryFilters;
  initialPage: DirectoryPage | null;
  facets: DirectoryFacets | null;
  isAdmin: boolean;
}

const SEARCH_DELAY_MS = 300;

const STATUS_STYLE: Record<DirectoryStatus, string> = {
  ambassador_confirmed: "bg-[var(--brand-light)] text-white",
  roster: "bg-[var(--brand)] text-white",
  ambassador_candidate: "border border-[var(--brand-light)] text-[var(--brand-light)]",
  applicant: "bg-[#f1f5f9] text-[#475569]",
};

export function StatusBadge({ status }: { status: DirectoryStatus }) {
  return (
    <span className={cn("inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold",
      STATUS_STYLE[status])}>
      {STATUS_LABEL[status]}
    </span>
  );
}

export function SelfReported() {
  return (
    <span title="Self-reported on the signup form. Not measured."
          className="ml-1 rounded bg-[var(--brand-pale)] px-1 py-px text-[10px] font-medium text-[#8a7243]">
      self-reported
    </span>
  );
}

function Followers({ person }: { person: DirectoryPerson }) {
  const { text, selfReported } = followerLabel(person);
  return (
    <span className="tabular-nums">
      {text}
      {selfReported && <SelfReported />}
    </span>
  );
}

const selectClass =
  "min-w-0 rounded-lg border border-[#e2e8f0] bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)]";

export default function AthleteDirectoryView({ initialFilters, initialPage, facets, isAdmin }: Props) {
  const [filters, setFilters] = useState<DirectoryFilters>(initialFilters);
  const [search, setSearch] = useState(initialFilters.q);
  const [data, setData] = useState<DirectoryPage | null>(initialPage);
  const [error, setError] = useState<string | null>(initialPage ? null : "The athlete list did not load.");
  // The backend query the shown results (or error) belong to. Loading while
  // it lags behind the current filters.
  const apiQuery = filtersToApiQuery(filters);
  const [settledQuery, setSettledQuery] = useState(() => filtersToApiQuery(initialFilters));
  const loading = settledQuery !== apiQuery;
  const firstRender = useRef(true);

  // Debounce typing into the search box.
  useEffect(() => {
    if (search === filters.q) return;
    const t = setTimeout(() => setFilters((f) => ({ ...f, q: search, page: 0 })), SEARCH_DELAY_MS);
    return () => clearTimeout(t);
  }, [search, filters.q]);

  // Fetch whenever the filters change, and keep the URL shareable.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
    } else {
      const pageQuery = filtersToPageQuery(filters);
      window.history.replaceState(null, "", pageQuery ? `${DIRECTORY_PATH}?${pageQuery}` : DIRECTORY_PATH);
    }
  }, [filters]);

  useEffect(() => {
    if (apiQuery === settledQuery) return;
    const ctrl = new AbortController();
    fetch(`/api/proxy/api/athlete-directory?${apiQuery}`, { signal: ctrl.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Error ${r.status}`);
        return r.json() as Promise<DirectoryPage>;
      })
      .then((page) => {
        setData(page);
        setError(null);
        setSettledQuery(apiQuery);
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setError(e.message || "The athlete list did not load.");
        setSettledQuery(apiQuery);
      });
    return () => ctrl.abort();
  }, [apiQuery, settledQuery]);

  const set = <K extends keyof DirectoryFilters>(name: K, value: DirectoryFilters[K]) =>
    setFilters((f) => ({ ...f, [name]: value, page: 0 }));

  const reset = () => {
    setSearch("");
    setFilters({ ...EMPTY_FILTERS, sort: filters.sort });
  };

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const exportHref = `/api/athlete-directory/export?${filtersToApiQuery(filters, false)}`;
  const nFilters = activeFilterCount(filters);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-[#0f172a]">Athletes</h1>
          <p className="text-sm text-[#64748b]">
            Roster, ambassadors and signups in one list.
            {facets ? ` ${facets.total.toLocaleString()} athletes in all.` : ""}
          </p>
        </div>
        {isAdmin && (
          <a href={exportHref}
             className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--brand)] px-3 py-2 text-sm font-medium text-white hover:opacity-90">
            <Download size={14} /> Export CSV
          </a>
        )}
      </div>

      {/* Search and filters */}
      <div className="space-y-3 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
        <label className="relative block">
          <span className="sr-only">Search athletes</span>
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, handle, school or sport"
            className="w-full rounded-lg border border-[#e2e8f0] bg-white py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
          />
        </label>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <select aria-label="Sport" value={filters.sport} onChange={(e) => set("sport", e.target.value)} className={selectClass}>
            <option value="">All sports</option>
            {facets?.sport.map((v) => <option key={v.value} value={v.value}>{v.value} ({v.count})</option>)}
          </select>
          <select aria-label="School" value={filters.school} onChange={(e) => set("school", e.target.value)} className={selectClass}>
            <option value="">All schools</option>
            {facets?.school.map((v) => <option key={v.value} value={v.value}>{v.value} ({v.count})</option>)}
          </select>
          <select aria-label="Campus channel" value={filters.campus} onChange={(e) => set("campus", e.target.value)} className={selectClass}>
            <option value="">All campus channels</option>
            {facets?.campus.map((v) => <option key={v.value} value={v.value}>{v.value} ({v.count})</option>)}
          </select>
          <select aria-label="Followers" value={filters.followers} onChange={(e) => set("followers", e.target.value)} className={selectClass}>
            {FOLLOWER_RANGES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {(["", ...Object.keys(STATUS_LABEL)] as (DirectoryStatus | "")[]).map((s) => (
            <button key={s || "all"} type="button" onClick={() => set("status", s)}
                    className={cn("rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                      filters.status === s
                        ? "border-[var(--brand)] bg-[var(--brand)] text-white"
                        : "border-[#e2e8f0] text-[#475569] hover:border-[var(--brand-light)]")}>
              {s ? STATUS_LABEL[s] : "Everyone"}
            </button>
          ))}
          <span className="hidden h-4 w-px bg-[#e2e8f0] sm:inline-block" />
          {([["", "Any consent"], ["true", "Partner consent"], ["false", "No partner consent"]] as const).map(([v, label]) => (
            <button key={v || "any"} type="button" onClick={() => set("partner_consent", v)}
                    className={cn("rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                      filters.partner_consent === v
                        ? "border-[var(--brand-light)] bg-[var(--brand-pale)] text-[#8a7243]"
                        : "border-[#e2e8f0] text-[#475569] hover:border-[var(--brand-light)]")}>
              {label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#f1f5f9] pt-3">
          <p className="text-sm text-[#64748b]" aria-live="polite">
            {loading ? "Loading…" : resultRange(total, filters.page, items.length)}
            {(nFilters > 0 || filters.q) && (
              <button type="button" onClick={reset}
                      className="ml-2 inline-flex items-center gap-0.5 text-xs font-medium text-[var(--brand)] hover:underline">
                <X size={12} /> Clear
              </button>
            )}
          </p>
          <label className="flex items-center gap-2 text-sm text-[#64748b]">
            Sort
            <select value={filters.sort} onChange={(e) => set("sort", e.target.value as DirectorySort)} className={selectClass}>
              {(Object.keys(SORT_LABEL) as DirectorySort[]).map((s) => <option key={s} value={s}>{SORT_LABEL[s]}</option>)}
            </select>
          </label>
        </div>
      </div>

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      )}

      {!error && items.length === 0 && !loading && (
        <p className="rounded-2xl border border-[#e2e8f0] bg-white px-4 py-10 text-center text-sm text-[#64748b]">
          No athletes match these filters.
        </p>
      )}

      {items.length > 0 && (
        <div className={cn("transition-opacity", loading && "opacity-60")}>
          {/* Phones: cards */}
          <ul className="space-y-2 md:hidden">
            {items.map((p) => (
              <li key={p.key}>
                <Link href={personPath(p.key)}
                      className="flex items-center gap-3 rounded-xl border border-[#e2e8f0] bg-white p-3 shadow-sm">
                  <AthleteAvatar name={p.display_name} src={p.profile_pic_url} size={44} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate font-semibold text-[#0f172a]">{p.display_name}</p>
                      <StatusBadge status={p.status} />
                    </div>
                    <p className="truncate text-xs text-[#64748b]">
                      {[p.sport, p.school].filter(Boolean).join(" · ") || "No sport or school yet"}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-[#475569]">
                      {p.ig_handle && <span className="truncate">@{p.ig_handle}</span>}
                      <span><Followers person={p} /> followers</span>
                      {p.collab_views > 0 && <span className="tabular-nums">{fmt(p.collab_views)} collab views</span>}
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>

          {/* Desktop: table */}
          <div className="hidden overflow-x-auto rounded-2xl border border-[#e2e8f0] bg-white shadow-sm md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#e2e8f0] text-left text-xs font-semibold uppercase tracking-wide text-[#64748b]">
                  <th className="px-4 py-3">Athlete</th>
                  <th className="px-4 py-3">Sport</th>
                  <th className="px-4 py-3">School</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Instagram</th>
                  <th className="px-4 py-3 text-right">Followers</th>
                  <th className="px-4 py-3 text-right">Collab views</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.key} className="border-b border-[#f1f5f9] last:border-0 hover:bg-[#f8fafc]">
                    <td className="px-4 py-2.5">
                      <Link href={personPath(p.key)} className="flex items-center gap-3">
                        <AthleteAvatar name={p.display_name} src={p.profile_pic_url} size={32} />
                        <span className="font-medium text-[var(--brand)] hover:underline">{p.display_name}</span>
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-[#475569]">{p.sport ?? "—"}</td>
                    <td className="px-4 py-2.5 text-[#475569]">{p.school ?? "—"}</td>
                    <td className="px-4 py-2.5"><StatusBadge status={p.status} /></td>
                    <td className="px-4 py-2.5 text-[#475569]">{p.ig_handle ? `@${p.ig_handle}` : "—"}</td>
                    <td className="px-4 py-2.5 text-right"><Followers person={p} /></td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{p.collab_views > 0 ? fmt(p.collab_views) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pages > 1 && (
        <nav className="flex items-center justify-center gap-3 text-sm" aria-label="Pages">
          <button type="button" disabled={filters.page === 0 || loading}
                  onClick={() => setFilters((f) => ({ ...f, page: f.page - 1 }))}
                  className="rounded-lg border border-[#e2e8f0] bg-white px-3 py-1.5 disabled:opacity-40">
            Previous
          </button>
          <span className="text-[#64748b]">Page {filters.page + 1} of {pages}</span>
          <button type="button" disabled={filters.page + 1 >= pages || loading}
                  onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}
                  className="rounded-lg border border-[#e2e8f0] bg-white px-3 py-1.5 disabled:opacity-40">
            Next
          </button>
        </nav>
      )}
    </div>
  );
}

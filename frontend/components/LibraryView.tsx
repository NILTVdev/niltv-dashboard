"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ExternalLink, Eye, Film, Search, Tag, X } from "lucide-react";
import type { LibraryFacetKey, LibraryFacets, LibraryItem, LibraryPage, LibraryStatus } from "@/lib/types";
import {
  FACETS, LIBRARY_PATH, NO_FILTERS, PAGE_SIZE, SORTS,
  activeFilterCount, athleteHref, athleteLabel, effectiveSort, fmtDuration, libraryQuery,
  needsTagging, pageQuery, qcLabel, staffAdminUrl, syncStatusLine, tagChips,
  type LibraryFilters, type LibrarySort,
} from "@/lib/library";
import { cn, fmt, fmtDate } from "@/lib/utils";

const API = "/api/proxy/api/library";
const SEARCH_DELAY_MS = 300;
// Where clip labels are edited. null hides the links (NEXT_PUBLIC_STAFF_ADMIN_URL unset).
const STAFF_ADMIN_URL = staffAdminUrl();

interface Props {
  initialFilters: LibraryFilters;
  initialSort: LibrarySort;
  initialQuery: string;
  initialPage: LibraryPage | null;
  initialFacets: LibraryFacets | null;
  status: LibraryStatus | null;
}

interface Loaded {
  qs: string;
  page: LibraryPage | null;
  facets: LibraryFacets | null;
  error: boolean;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export default function LibraryView({
  initialFilters, initialSort, initialQuery, initialPage, initialFacets, status,
}: Props) {
  const [qInput, setQInput] = useState(initialFilters.q);
  const [q, setQ] = useState(initialFilters.q);
  const [facets, setFacets] = useState<LibraryFilters["facets"]>(initialFilters.facets);
  const [needsTaggingOnly, setNeedsTaggingOnly] = useState(initialFilters.needsTagging);
  const [hasVideo, setHasVideo] = useState(initialFilters.hasVideo);
  const [postedFrom, setPostedFrom] = useState(initialFilters.postedFrom);
  const [postedTo, setPostedTo] = useState(initialFilters.postedTo);
  const [sort, setSort] = useState<LibrarySort>(initialSort);
  const [loaded, setLoaded] = useState<Loaded>({
    qs: initialQuery, page: initialPage, facets: initialFacets, error: initialPage === null,
  });
  const [loadingMore, setLoadingMore] = useState(false);
  const [open, setOpen] = useState<LibraryItem | null>(null);

  // Search as you type, once typing pauses.
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput), SEARCH_DELAY_MS);
    return () => clearTimeout(t);
  }, [qInput]);

  const filters: LibraryFilters = useMemo(
    () => ({ q, facets, needsTagging: needsTaggingOnly, hasVideo, postedFrom, postedTo }),
    [q, facets, needsTaggingOnly, hasVideo, postedFrom, postedTo],
  );
  const shownSort = effectiveSort(filters, sort);
  const qs = libraryQuery(filters, { sort, limit: PAGE_SIZE });
  const facetQs = libraryQuery(filters);
  const loading = loaded.qs !== qs;
  const urlQuery = pageQuery(filters, sort);

  // Keep the address bar in step with the filters, so a filtered view can be shared.
  useEffect(() => {
    const want = urlQuery ? `?${urlQuery}` : "";
    if (window.location.search !== want) window.history.replaceState(null, "", `${LIBRARY_PATH}${want}`);
  }, [urlQuery]);

  useEffect(() => {
    if (qs === loaded.qs) return;
    const ctrl = new AbortController();
    Promise.all([
      getJson<LibraryPage>(`${API}/?${qs}`, ctrl.signal),
      getJson<LibraryFacets>(`${API}/facets${facetQs ? `?${facetQs}` : ""}`, ctrl.signal).catch(() => null),
    ])
      .then(([page, f]) => setLoaded({ qs, page, facets: f, error: false }))
      .catch(() => {
        if (!ctrl.signal.aborted) setLoaded((prev) => ({ ...prev, qs, error: true }));
      });
    return () => ctrl.abort();
  }, [qs, facetQs, loaded.qs]);

  async function loadMore() {
    const page = loaded.page;
    if (!page || loadingMore) return;
    setLoadingMore(true);
    try {
      const more = await getJson<LibraryPage>(
        `${API}/?${libraryQuery(filters, { sort, limit: PAGE_SIZE, offset: page.items.length })}`);
      setLoaded((prev) => prev.qs !== qs || !prev.page ? prev : {
        ...prev, page: { ...more, items: [...prev.page.items, ...more.items] },
      });
    } catch {
      // The button stays; a second press retries.
    } finally {
      setLoadingMore(false);
    }
  }

  function setFacet(key: LibraryFacetKey, value: string) {
    setFacets((prev) => ({ ...prev, [key]: value || undefined }));
  }

  function clearAll() {
    setQInput("");
    setQ("");
    setFacets(NO_FILTERS.facets);
    setNeedsTaggingOnly(false);
    setHasVideo(false);
    setPostedFrom("");
    setPostedTo("");
  }

  const syncLine = syncStatusLine(status);
  const neverSynced = !status?.last_ok_run;
  const items = loaded.page?.items ?? [];
  const total = loaded.page?.total ?? 0;
  const filterCount = activeFilterCount(filters);

  return (
    <div className="flex flex-col gap-6 min-w-0">
      {/* Header + search */}
      <div className="rounded-2xl bg-[var(--brand)] text-white p-5 sm:p-6 flex flex-col gap-4 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-xl font-bold">Library</h1>
            <p className="text-sm text-white/70">
              {syncLine ?? "Not synced yet."}
            </p>
          </div>
          {status && status.needs_tagging > 0 && (
            <button
              onClick={() => setNeedsTaggingOnly((v) => !v)}
              className="text-xs font-medium text-[var(--brand-light)] hover:underline"
            >
              {fmt(status.needs_tagging)} need tagging
            </button>
          )}
        </div>
        <label className="relative block">
          <span className="sr-only">Search clips</span>
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/50" />
          <input
            type="search"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Search titles, captions, athletes and tags"
            className="w-full rounded-lg bg-white/10 border border-white/15 pl-9 pr-3 py-2.5 text-sm text-white placeholder:text-white/50 focus:outline-none focus:border-[var(--brand-light)]"
          />
        </label>
      </div>

      {neverSynced && !items.length ? (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm py-16 px-6 text-center">
          <Film size={28} className="mx-auto text-[var(--brand-light)] mb-3" />
          <p className="text-sm font-semibold text-[#0f172a]">The library is empty.</p>
          <p className="text-sm text-[#64748b] mt-1">It fills after the app&apos;s next ingest run.</p>
        </div>
      ) : (
        <>
          {/* Filters */}
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-4 flex flex-col gap-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
              {FACETS.map(({ key, label }) => {
                const values = loaded.facets?.[key] ?? [];
                const selected = facets[key] ?? "";
                return (
                  <label key={key} className="flex flex-col gap-1 min-w-0">
                    <span className="text-[11px] font-medium text-[#64748b]">{label}</span>
                    <select
                      value={selected}
                      onChange={(e) => setFacet(key, e.target.value)}
                      className={cn(
                        "w-full min-w-0 truncate rounded-md border px-2 py-1.5 text-sm bg-white",
                        selected ? "border-[var(--brand-light)] text-[#0f172a]" : "border-[#e2e8f0] text-[#64748b]",
                      )}
                    >
                      <option value="">All</option>
                      {selected && !values.some((v) => v.value === selected) && (
                        <option value={selected}>{key === "qc_state" ? qcLabel(selected) : selected}</option>
                      )}
                      {values.map((v) => (
                        <option key={v.value} value={v.value}>
                          {key === "qc_state" ? qcLabel(v.value) : v.label} ({v.count})
                        </option>
                      ))}
                    </select>
                  </label>
                );
              })}
              <DateField label="Posted from" value={postedFrom} max={postedTo || undefined} onChange={setPostedFrom} />
              <DateField label="Posted to" value={postedTo} min={postedFrom || undefined} onChange={setPostedTo} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Toggle on={needsTaggingOnly} onClick={() => setNeedsTaggingOnly((v) => !v)}>
                <Tag size={12} /> Needs tagging
              </Toggle>
              <Toggle on={hasVideo} onClick={() => setHasVideo((v) => !v)}>
                <Film size={12} /> Has video
              </Toggle>
              {(filterCount > 0 || q) && (
                <button onClick={clearAll} className="text-xs text-[#64748b] hover:text-[#0f172a] underline">
                  Clear all
                </button>
              )}
              <label className="ml-auto flex items-center gap-2 text-xs text-[#64748b]">
                Sort
                <select
                  value={shownSort}
                  onChange={(e) => setSort(e.target.value as LibrarySort)}
                  className="rounded-md border border-[#e2e8f0] px-2 py-1 text-sm text-[#0f172a] bg-white"
                >
                  {SORTS.filter((s) => s.key !== "relevance" || q.trim()).map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </label>
            </div>
            {needsTaggingOnly && (
              <p className="text-xs text-[#64748b] bg-[var(--brand-pale)] rounded-md px-3 py-2">
                These clips are not marked ready. Labels are edited in the app&apos;s{" "}
                {STAFF_ADMIN_URL ? (
                  <a href={STAFF_ADMIN_URL} target="_blank" rel="noopener noreferrer"
                     className="font-medium text-[#8a6d2f] underline underline-offset-2">
                    staff admin tool
                  </a>
                ) : "staff admin tool"}.
                Changes show here after the next sync.
              </p>
            )}
          </div>

          {/* Results */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-[#64748b]">
              {loaded.error ? "Could not load the library. Try again." : `${total.toLocaleString("en-US")} clip${total === 1 ? "" : "s"}`}
            </span>
            {loading && <span className="text-xs text-[#94a3b8]">Loading</span>}
          </div>

          {!loaded.error && !items.length ? (
            <div className="py-12 text-center text-sm text-[#94a3b8]">No clips match. Try fewer filters.</div>
          ) : (
            <div className={cn("grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 transition-opacity",
                               loading && "opacity-60")}>
              {items.map((item) => <ClipCard key={item.content_id} item={item} onOpen={() => setOpen(item)} />)}
            </div>
          )}

          {items.length < total && (
            <button
              onClick={loadMore}
              disabled={loadingMore || loading}
              className="self-center rounded-lg border border-[#e2e8f0] bg-white px-4 py-2 text-sm font-medium text-[#0f172a] hover:bg-[var(--brand-pale)] disabled:opacity-50"
            >
              {loadingMore ? "Loading" : `Show more (${(total - items.length).toLocaleString("en-US")} left)`}
            </button>
          )}
        </>
      )}

      {open && <ClipDrawer item={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function DateField({ label, value, min, max, onChange }: {
  label: string; value: string; min?: string; max?: string; onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="text-[11px] font-medium text-[#64748b]">{label}</span>
      <input
        type="date"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-full min-w-0 rounded-md border px-2 py-1.5 text-sm bg-white",
          value ? "border-[var(--brand-light)] text-[#0f172a]" : "border-[#e2e8f0] text-[#64748b]",
        )}
      />
    </label>
  );
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        on ? "bg-[var(--brand)] border-[var(--brand)] text-white" : "border-[#e2e8f0] text-[#64748b] hover:bg-[#f8fafc]",
      )}
    >
      {children}
    </button>
  );
}

export function Poster({ item, className }: { item: LibraryItem; className?: string }) {
  if (!item.poster_url) {
    return (
      <div className={cn("flex items-center justify-center bg-gradient-to-b from-[#1c1c22] to-[var(--brand)]", className)}>
        <Film size={24} className="text-white/30" />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={item.poster_url} alt="" loading="lazy" className={cn("object-cover bg-[var(--brand)]", className)} />
  );
}

function ClipCard({ item, onOpen }: { item: LibraryItem; onOpen: () => void }) {
  const chips = tagChips(item);
  const duration = fmtDuration(item.duration_sec);
  const views = item.performance.views;
  return (
    <button
      onClick={onOpen}
      className="group text-left min-w-0 flex flex-col gap-2 focus:outline-none"
    >
      <div className="relative w-full aspect-[9/16] overflow-hidden rounded-xl border border-[#e2e8f0] group-hover:border-[var(--brand-light)] group-focus-visible:ring-2 group-focus-visible:ring-[var(--brand-light)]">
        <Poster item={item} className="absolute inset-0 h-full w-full" />
        <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-1 bg-gradient-to-t from-black/80 to-transparent px-2 pb-1.5 pt-6 text-[11px] font-medium text-white">
          <span className="flex items-center gap-1">
            <Eye size={12} /> {views != null ? fmt(views) : "—"}
          </span>
          {duration && <span>{duration}</span>}
        </div>
        {(needsTagging(item) || item.removed || item.status !== "published") && (
          <div className="absolute left-1.5 top-1.5 flex flex-col items-start gap-1">
            {needsTagging(item) && <Badge tone="gold">{qcLabel(item.qc_state)}</Badge>}
            {item.status && item.status !== "published" && <Badge tone="dark">{qcLabel(item.status)}</Badge>}
            {item.removed && <Badge tone="dark">Removed</Badge>}
          </div>
        )}
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-[#0f172a] leading-snug line-clamp-2 break-words">{item.title || "Untitled"}</p>
        <p className="text-[11px] text-[#64748b] truncate">
          {[item.channel_name, item.posted_at ? fmtDate(item.posted_at) : null].filter(Boolean).join(" · ") || "—"}
        </p>
        {chips.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {chips.slice(0, 3).map((c) => <Chip key={c}>{c}</Chip>)}
            {chips.length > 3 && <Chip>+{chips.length - 3}</Chip>}
          </div>
        )}
      </div>
    </button>
  );
}

function Badge({ tone, children }: { tone: "gold" | "dark"; children: React.ReactNode }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold",
                        tone === "gold" ? "bg-[var(--brand-light)] text-[var(--brand)]" : "bg-black/70 text-white")}>
      {children}
    </span>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="max-w-full truncate rounded bg-[var(--brand-pale)] px-1.5 py-0.5 text-[10px] font-medium text-[#5b4a22]">
      {children}
    </span>
  );
}

function ClipDrawer({ item, onClose }: { item: LibraryItem; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const p = item.performance;
  const types = item.content_types.length ? item.content_types : item.content_type ? [item.content_type] : [];
  const duration = fmtDuration(item.duration_sec);

  return (
    <div className="fixed inset-0 z-[60] flex justify-end" role="dialog" aria-modal="true" aria-label={item.title}>
      <button aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/50" />
      <div className="relative h-full w-full max-w-lg overflow-y-auto overflow-x-hidden bg-white shadow-xl">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 bg-[var(--brand)] px-5 py-4 text-white">
          <div className="min-w-0">
            <h2 className="text-base font-semibold leading-snug break-words">{item.title || "Untitled"}</h2>
            <p className="text-xs text-white/70">
              {[item.channel_name, item.posted_at ? fmtDate(item.posted_at) : null, duration].filter(Boolean).join(" · ")}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="shrink-0 rounded-md p-1 text-white/80 hover:bg-white/10">
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-col gap-5 p-5">
          <div className="mx-auto w-full max-w-[18rem] aspect-[9/16] overflow-hidden rounded-xl bg-[var(--brand)]">
            {item.video_url ? (
              <video
                key={item.content_id}
                src={item.video_url}
                poster={item.poster_url ?? undefined}
                controls
                playsInline
                preload="none"
                className="h-full w-full object-contain"
              />
            ) : (
              <Poster item={item} className="h-full w-full" />
            )}
          </div>

          <div className="flex flex-wrap gap-1.5">
            <Pill tone={needsTagging(item) ? "gold" : "plain"}>QC: {qcLabel(item.qc_state)}</Pill>
            <Pill tone="plain">Status: {qcLabel(item.status)}</Pill>
            {item.removed && <Pill tone="dark">Removed from the app</Pill>}
          </div>

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#64748b]">Performance</h3>
            <div className="grid grid-cols-3 gap-2">
              {([
                ["Views", p.views], ["Likes", p.likes], ["Comments", p.comments],
                ["Shares", p.shares], ["Saves", p.saves], ["Reach", p.reach],
              ] as const).map(([label, n]) => (
                <div key={label} className="rounded-lg border border-[#e2e8f0] px-2 py-1.5">
                  <div className="text-[10px] text-[#64748b]">{label}</div>
                  <div className="text-sm font-semibold text-[#0f172a]">{n != null ? fmt(n) : "—"}</div>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-[#94a3b8]">
              {!item.ig_post_id
                ? "Not from Instagram. No numbers to show."
                : !p.matched
                  ? "The Instagram pull has not picked up this post yet."
                  : p.source === "brand"
                    ? "Instagram numbers from the brand account pull. A dash means not reported."
                    : "Instagram numbers from the latest pull. A dash means not reported."}
            </p>
            {p.permalink && (
              <a href={p.permalink} target="_blank" rel="noopener noreferrer"
                 className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-[#8a6d2f] hover:underline">
                Open on Instagram <ExternalLink size={12} />
              </a>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-[#64748b]">Labels</h3>
              {STAFF_ADMIN_URL && (
                <a href={STAFF_ADMIN_URL} target="_blank" rel="noopener noreferrer"
                   title="Opens the staff admin tool. Find this clip on its Content tab."
                   className="inline-flex items-center gap-1 text-xs font-medium text-[#8a6d2f] hover:underline">
                  Edit in staff admin <ExternalLink size={12} />
                </a>
              )}
            </div>
            <TagRow label="Sport" values={item.sport ? [item.sport] : []} />
            <TagRow label="School" values={item.school ? [item.school] : []} />
            <TagRow label="Content type" values={types} />
            <TagRow label="Categories" values={item.categories} />
            <TagRow label="Sponsor" values={item.sponsor ? [item.sponsor] : []} />
            <TagRow label="Keywords" values={item.keywords} />
          </section>

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#64748b]">Athletes</h3>
            {item.athletes.length === 0 && item.unresolved_handles.length === 0 ? (
              <p className="text-sm text-[#94a3b8]">None tagged.</p>
            ) : (
              <ul className="flex flex-col gap-1 text-sm text-[#0f172a]">
                {item.athletes.map((a, i) => (
                  <li key={a.id ?? a.handle ?? i} className="break-words">
                    {athleteHref(a) ? (
                      <Link href={athleteHref(a)!} className="font-medium text-[var(--brand)] underline-offset-2 hover:underline">
                        {athleteLabel(a)}
                      </Link>
                    ) : athleteLabel(a)}
                    {a.name && a.handle && <span className="text-[#64748b]"> @{a.handle.replace(/^@/, "")}</span>}
                  </li>
                ))}
                {item.unresolved_handles.map((h) => (
                  <li key={h} className="break-words text-[#64748b]">@{h.replace(/^@/, "")} <span className="text-xs">(not matched to an athlete)</span></li>
                ))}
              </ul>
            )}
          </section>

          {item.summary && (
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#64748b]">Summary</h3>
              <p className="text-sm text-[#0f172a] break-words">{item.summary}</p>
            </section>
          )}
          {item.caption && (
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#64748b]">Caption</h3>
              <p className="text-sm text-[#334155] whitespace-pre-line break-words">{item.caption}</p>
            </section>
          )}
          <p className="text-[11px] text-[#94a3b8] break-all">
            {item.content_id} · first seen {fmtDate(item.first_seen_at)} · synced {fmtDate(item.last_synced_at)}
          </p>
        </div>
      </div>
    </div>
  );
}

function Pill({ tone, children }: { tone: "gold" | "plain" | "dark"; children: React.ReactNode }) {
  return (
    <span className={cn(
      "rounded-full px-2.5 py-0.5 text-xs font-medium",
      tone === "gold" && "bg-[var(--brand-light)] text-[var(--brand)]",
      tone === "plain" && "bg-[#f1f5f9] text-[#475569]",
      tone === "dark" && "bg-[var(--brand)] text-white",
    )}>
      {children}
    </span>
  );
}

function TagRow({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="w-28 shrink-0 text-[#64748b]">{label}</span>
      {values.length ? (
        <div className="flex min-w-0 flex-wrap gap-1">
          {values.map((v) => <Chip key={v}>{v}</Chip>)}
        </div>
      ) : (
        <span className="text-[#94a3b8]">—</span>
      )}
    </div>
  );
}

/**
 * Pure helpers for the Library page (components/LibraryView.tsx): query
 * strings for /api/library, labels and the sync status line. No fetches here,
 * so lib/library.test.ts can cover them.
 */

import type { LibraryAthlete, LibraryFacetKey, LibraryItem, LibraryStatus } from "./types";

export type LibrarySort = "relevance" | "newest" | "views" | "engaged";

export const SORTS: { key: LibrarySort; label: string }[] = [
  { key: "relevance", label: "Best match" },
  { key: "newest", label: "Newest" },
  { key: "views", label: "Most viewed" },
  { key: "engaged", label: "Most engaged" },
];

export const FACETS: { key: LibraryFacetKey; label: string }[] = [
  { key: "sport", label: "Sport" },
  { key: "school", label: "School" },
  { key: "channel", label: "Channel" },
  { key: "category", label: "Category" },
  { key: "content_type", label: "Content type" },
  { key: "sponsor", label: "Sponsor" },
  { key: "qc_state", label: "QC" },
];

export const PAGE_SIZE = 48;
export const READY = "ready";

export interface LibraryFilters {
  q: string;
  facets: Partial<Record<LibraryFacetKey, string>>;
  needsTagging: boolean;
  hasVideo: boolean;
}

export const NO_FILTERS: LibraryFilters = { q: "", facets: {}, needsTagging: false, hasVideo: false };

/** Best match only means something with a search; otherwise newest. */
export function effectiveSort(filters: LibraryFilters, sort: LibrarySort): LibrarySort {
  return sort === "relevance" && !filters.q.trim() ? "newest" : sort;
}

/** Query string for /api/library and /api/library/facets (no leading "?"). */
export function libraryQuery(
  filters: LibraryFilters,
  opts: { sort?: LibrarySort; offset?: number; limit?: number } = {},
): string {
  const p = new URLSearchParams();
  const q = filters.q.trim();
  if (q) p.set("q", q);
  for (const { key } of FACETS) {
    const v = filters.facets[key];
    if (v) p.set(key, v);
  }
  if (filters.needsTagging) p.set("needs_tagging", "true");
  if (filters.hasVideo) p.set("has_video", "true");
  if (opts.sort) p.set("sort", effectiveSort(filters, opts.sort));
  if (opts.limit != null) p.set("limit", String(opts.limit));
  if (opts.offset) p.set("offset", String(opts.offset));
  return p.toString();
}

export function activeFilterCount(filters: LibraryFilters): number {
  return Object.values(filters.facets).filter(Boolean).length
    + (filters.needsTagging ? 1 : 0) + (filters.hasVideo ? 1 : 0);
}

/** "needs-review" -> "Needs review"; null -> "Not checked". */
export function qcLabel(state: string | null | undefined): string {
  if (!state) return "Not checked";
  const words = state.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function needsTagging(item: Pick<LibraryItem, "qc_state">): boolean {
  return (item.qc_state ?? "") !== READY;
}

/** The labels shown as chips on a card, in a fixed order, without repeats. */
export function tagChips(item: LibraryItem): string[] {
  const types = item.content_types.length ? item.content_types : item.content_type ? [item.content_type] : [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const t of [item.sport, item.school, ...types, ...item.categories, item.sponsor]) {
    const v = (t ?? "").trim();
    if (!v || seen.has(v.toLowerCase())) continue;
    seen.add(v.toLowerCase());
    out.push(v);
  }
  return out;
}

export function athleteLabel(a: LibraryAthlete): string {
  if (a.name) return a.name;
  if (a.handle) return `@${a.handle.replace(/^@/, "")}`;
  return a.id ?? "Unknown athlete";
}

/** 24.5 -> "0:25"; 125 -> "2:05". */
export function fmtDuration(sec: number | null | undefined): string | null {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return null;
  const total = Math.round(sec);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const mins = Math.floor((now.getTime() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** "Last synced 2 hours ago. 698 clips." null before the first good sync. */
export function syncStatusLine(status: LibraryStatus | null, now: Date = new Date()): string | null {
  const ok = status?.last_ok_run;
  if (!status || !ok) return null;
  const clips = `${status.items.toLocaleString("en-US")} clip${status.items === 1 ? "" : "s"}`;
  let line = `Last synced ${relativeTime(ok.received_at, now)}. ${clips}.`;
  const last = status.last_run;
  if (last && !last.ok && last.id !== ok.id) line += ` The latest sync failed ${relativeTime(last.received_at, now)}.`;
  return line;
}

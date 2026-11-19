/**
 * Athlete directory helpers: filter state <-> query string, labels, and the
 * small formatting rules the list and detail pages share. Client-safe (no env).
 */

import type {
  DirectoryPerson, DirectoryPost, DirectorySort, Post,
} from "./types";
import { fmt } from "./utils";

export const DIRECTORY_PATH = "/athletes";
export const PAGE_SIZE = 50;

export const personPath = (key: string) => `${DIRECTORY_PATH}/${encodeURIComponent(key)}`;

/** Card title for the library clips on an athlete page. */
export function clipsTitle(shown: number, total: number): string {
  if (!total) return "Library clips";
  return shown < total ? `Library clips (newest ${shown} of ${fmt(total)})` : `Library clips (${fmt(total)})`;
}

export const SORT_LABEL: Record<DirectorySort, string> = {
  followers: "Most followers",
  collab_views: "Most collab views",
  name: "Name",
  newest: "Newest",
};

/** Follower buckets offered in the filter, as inclusive bounds. */
export const FOLLOWER_RANGES = [
  { key: "", label: "Any followers" },
  { key: "lt1k", label: "Under 1K", max: 999 },
  { key: "1k-10k", label: "1K to 10K", min: 1_000, max: 9_999 },
  { key: "10k-100k", label: "10K to 100K", min: 10_000, max: 99_999 },
  { key: "100k+", label: "100K and up", min: 100_000 },
] as const satisfies readonly { key: string; label: string; min?: number; max?: number }[];

export interface DirectoryFilters {
  q: string;
  sport: string;
  school: string;
  campus: string;
  followers: string; // a FOLLOWER_RANGES key
  sort: DirectorySort;
  page: number; // 0-based
}

export const EMPTY_FILTERS: DirectoryFilters = {
  q: "", sport: "", school: "", campus: "", followers: "", sort: "followers", page: 0,
};

const SORTS = Object.keys(SORT_LABEL) as DirectorySort[];

type ParamSource = { get(name: string): string | null };

/** Filters from the page URL. Unknown values fall back to the defaults. */
export function filtersFromParams(params: ParamSource): DirectoryFilters {
  const pick = (name: string) => (params.get(name) ?? "").trim();
  const sort = pick("sort") as DirectorySort;
  const followers = pick("followers");
  const page = Number.parseInt(pick("page"), 10);
  return {
    q: pick("q"),
    sport: pick("sport"),
    school: pick("school"),
    campus: pick("campus"),
    followers: FOLLOWER_RANGES.some((r) => r.key === followers) ? followers : "",
    sort: SORTS.includes(sort) ? sort : EMPTY_FILTERS.sort,
    page: Number.isFinite(page) && page > 0 ? page : 0,
  };
}

/** The page URL's query string: only what differs from the defaults. */
export function filtersToPageQuery(f: DirectoryFilters): string {
  const p = new URLSearchParams();
  for (const name of ["q", "sport", "school", "campus", "followers"] as const) {
    const v = f[name].trim();
    if (v) p.set(name, v);
  }
  if (f.sort !== EMPTY_FILTERS.sort) p.set("sort", f.sort);
  if (f.page > 0) p.set("page", String(f.page));
  return p.toString();
}

/** The backend query string (/api/athlete-directory/?...). Paging is left
 * out when `paged` is false (the CSV export takes every match). */
export function filtersToApiQuery(f: DirectoryFilters, paged = true): string {
  const p = new URLSearchParams();
  for (const name of ["q", "sport", "school", "campus"] as const) {
    const v = f[name].trim();
    if (v) p.set(name, v);
  }
  const range = FOLLOWER_RANGES.find((r) => r.key === f.followers);
  if (range && "min" in range) p.set("min_followers", String(range.min));
  if (range && "max" in range) p.set("max_followers", String(range.max));
  p.set("sort", f.sort);
  if (paged) {
    p.set("limit", String(PAGE_SIZE));
    p.set("offset", String(f.page * PAGE_SIZE));
  }
  return p.toString();
}

export function activeFilterCount(f: DirectoryFilters): number {
  return (["sport", "school", "campus", "followers"] as const).filter((name) => f[name] !== "").length;
}

/** Up to two initials for the photo placeholder. */
export function initials(name: string): string {
  const words = name.replace(/^@/, "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const letters = words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[words.length - 1][0];
  return letters.toUpperCase();
}

/** Follower count text plus whether to mark it self-reported. */
export function followerLabel(p: Pick<DirectoryPerson, "followers" | "followers_self_reported">): {
  text: string; selfReported: boolean;
} {
  if (p.followers == null) return { text: "—", selfReported: false };
  return { text: fmt(p.followers), selfReported: p.followers_self_reported };
}

/** "1–50 of 312" style range text for the result count. */
export function resultRange(total: number, page: number, count: number): string {
  if (total === 0 || count === 0) return "0 athletes";
  const start = page * PAGE_SIZE + 1;
  const end = page * PAGE_SIZE + count;
  const noun = total === 1 ? "athlete" : "athletes";
  return start === 1 && end === total ? `${total.toLocaleString()} ${noun}` :
    `${start.toLocaleString()} to ${end.toLocaleString()} of ${total.toLocaleString()} ${noun}`;
}

/** A NIL TV network post in the shape PostsGrid draws. Videos use their
 * thumbnail: the media URL of a reel is the mp4. */
export function toGridPost(p: DirectoryPost, i: number): Post {
  return {
    id: i,
    athlete_id: 0,
    ig_post_id: p.post_id,
    posted_at: p.publish_time,
    media_type: p.post_type,
    like_count: p.likes,
    comment_count: p.comments,
    permalink: p.permalink,
    caption: p.description,
    media_url: p.thumbnail_url ?? (p.post_type === "VIDEO" || p.post_type === "REELS" ? null : p.media_url),
  };
}

/** Profile URL for a handle (or the URL itself), or null when there is none. */
export function socialUrl(network: "instagram" | "tiktok" | "youtube" | "x", handle: string | null): string | null {
  if (!handle) return null;
  const h = handle.trim();
  if (/^https?:\/\//i.test(h)) return h;
  const bare = h.replace(/^@/, "");
  if (!bare) return null;
  switch (network) {
    case "instagram": return `https://instagram.com/${bare}`;
    case "tiktok": return `https://www.tiktok.com/@${bare}`;
    case "youtube": return `https://www.youtube.com/@${bare}`;
    case "x": return `https://x.com/${bare}`;
  }
}

/** Application `answers` JSON as label/value rows (strings, numbers, booleans
 * and lists of those; anything nested is skipped). */
export function answerRows(answers: unknown): { label: string; value: string }[] {
  if (!answers || typeof answers !== "object" || Array.isArray(answers)) return [];
  const rows: { label: string; value: string }[] = [];
  for (const [k, v] of Object.entries(answers as Record<string, unknown>)) {
    let value: string | null = null;
    if (typeof v === "string") value = v.trim() || null;
    else if (typeof v === "number") value = String(v);
    else if (typeof v === "boolean") value = v ? "Yes" : "No";
    else if (Array.isArray(v) && v.every((x) => ["string", "number"].includes(typeof x))) value = v.join(", ") || null;
    if (value) rows.push({ label: humanize(k), value });
  }
  return rows;
}

export function humanize(key: string): string {
  const spaced = key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").trim().toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

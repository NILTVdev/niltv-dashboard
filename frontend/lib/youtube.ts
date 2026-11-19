/**
 * Pure helpers for the YouTube page: sorting and filtering the loaded
 * uploads, and formatting durations and watch time. No React, no env, so
 * vitest covers them (lib/youtube.test.ts).
 */

import type { YoutubeVideo } from "./types";

export type VideoSort = "views" | "views_per_day" | "published" | "likes" | "comments";
export type VideoFormat = "all" | "shorts" | "long";

/** "45s", "3:05", "1:02:03". Null renders as a dash. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}

/** Watch hours with one decimal under 100, whole hours above. */
export function fmtHours(hours: number | null | undefined): string {
  if (hours == null) return "—";
  if (hours >= 100) return Math.round(hours).toLocaleString("en-US");
  return hours.toFixed(1);
}

export function fmtPercent(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(1)}%`;
}

/** "+12", "-3", "0", or a dash when the change is unknown. */
export function fmtChange(n: number | null | undefined, format: (v: number) => string = String): string {
  if (n == null) return "—";
  return n > 0 ? `+${format(n)}` : n < 0 ? `-${format(-n)}` : "0";
}

/** Views per day since publish, never dividing by less than one day. */
export function viewsPerDay(video: Pick<YoutubeVideo, "views" | "published_at">, nowMs: number): number | null {
  if (video.views == null || !video.published_at) return null;
  const days = Math.max((nowMs - new Date(video.published_at).getTime()) / 86_400_000, 1);
  return video.views / days;
}

export function filterVideos(videos: YoutubeVideo[], format: VideoFormat, query = ""): YoutubeVideo[] {
  const q = query.trim().toLowerCase();
  return videos.filter((v) => {
    if (format === "shorts" && v.is_short !== true) return false;
    if (format === "long" && v.is_short === true) return false;
    if (q && !(v.title ?? "").toLowerCase().includes(q)) return false;
    return true;
  });
}

function sortValue(v: YoutubeVideo, sort: VideoSort, nowMs: number): number | null {
  switch (sort) {
    case "views": return v.views;
    case "likes": return v.likes;
    case "comments": return v.comments;
    case "published": return v.published_at ? new Date(v.published_at).getTime() : null;
    case "views_per_day": return v.views_per_day ?? viewsPerDay(v, nowMs);
  }
}

/** Highest first; unknown values always last; ties keep a stable id order. */
export function sortVideos(videos: YoutubeVideo[], sort: VideoSort, nowMs: number): YoutubeVideo[] {
  return [...videos].sort((a, b) => {
    const va = sortValue(a, sort, nowMs);
    const vb = sortValue(b, sort, nowMs);
    if (va == null && vb == null) return a.video_id.localeCompare(b.video_id);
    if (va == null) return 1;
    if (vb == null) return -1;
    return vb - va || a.video_id.localeCompare(b.video_id);
  });
}

import type {
  Athlete, Snapshot, Post, ZoomphPost, ZoomphSummary, ZoomphDailyImpressions,
  BrandSnapshot, BrandPost, BrandSummary,
  NiltvNetworkPost, NiltvNetworkSummary,
  TrueBlueSnapshot, TrueBluePost, TrueBlueSummary,
  TrueBlueNetworkSummary, TrueBlueTopAccount, TrueBlueNetworkPost, NetworkMetricsOverTime,
  GA4Snapshot, GSCDailyTotal, GSCQuerySnapshot, GSCPageSnapshot,
  GA4Summary, GSCSummary,
} from "./types";

import { API_KEY, BACKEND_URL as BASE } from "./serverEnv";

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "X-API-Key": API_KEY },
    next: { revalidate: 300 },
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const getAthletes = () => apiFetch<Athlete[]>("/api/athletes/");
export const getAthlete = (id: number) => apiFetch<Athlete>(`/api/athletes/${id}`);
export const getSnapshots = (id: number) => apiFetch<Snapshot[]>(`/api/snapshots/athletes/${id}`);
export const getPosts = (id: number) => apiFetch<Post[]>(`/api/posts/athletes/${id}`);
export const getZoomphPosts = (limit = 200, author?: string) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (author) params.set("author", author);
  return apiFetch<ZoomphPost[]>(`/api/zoomph/?${params}`);
};
export const getZoomphSummary = (author?: string) => {
  const params = author ? `?author=${encodeURIComponent(author)}` : "";
  return apiFetch<ZoomphSummary[]>(`/api/zoomph/summary${params}`);
};
export const getZoomphImpressionsByDay = (author?: string, startDate?: string, endDate?: string) => {
  const params = new URLSearchParams();
  if (author) params.set("author", author);
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  const qs = params.toString();
  return apiFetch<ZoomphDailyImpressions[]>(`/api/zoomph/impressions-by-day${qs ? `?${qs}` : ""}`);
};
export const getZoomphAuthors = () => apiFetch<string[]>("/api/zoomph/authors");

// Owned brand Instagram accounts (@niltv default, @nilstar, ...)
export const getBrandProfile = (account = "niltv") => apiFetch<BrandSnapshot | null>(`/api/brand/profile?account=${account}`);
export const getBrandSnapshots = (account = "niltv") => apiFetch<BrandSnapshot[]>(`/api/brand/snapshots?account=${account}`);
export const getBrandPosts = (limit = 200, account = "niltv") => apiFetch<BrandPost[]>(`/api/brand/posts?limit=${limit}&account=${account}`);
export const getBrandSummary = (account = "niltv") => apiFetch<BrandSummary>(`/api/brand/summary?account=${account}`);
export const getNiltvNetworkPosts = (limit = 500) => apiFetch<NiltvNetworkPost[]>(`/api/brand/network/posts?limit=${limit}`);
export const getNiltvNetworkSummary = () => apiFetch<NiltvNetworkSummary>("/api/brand/network/summary");

// TrueBlue TV
export const getTrueBlueProfile = () => apiFetch<TrueBlueSnapshot | null>("/api/trueblue/profile");
export const getTrueBlueSnapshots = () => apiFetch<TrueBlueSnapshot[]>("/api/trueblue/snapshots");
export const getTrueBluePosts = (limit = 200) => apiFetch<TrueBluePost[]>(`/api/trueblue/posts?limit=${limit}`);
export const getTrueBlueSummary = () => apiFetch<TrueBlueSummary>("/api/trueblue/summary");
export const getTrueBlueNetworkSummary = () => apiFetch<TrueBlueNetworkSummary>("/api/trueblue/network/summary");
export const getTrueBlueTopAccounts = () => apiFetch<TrueBlueTopAccount[]>("/api/trueblue/network/top-accounts");
export const getTrueBlueNetworkPosts = (limit = 500) => apiFetch<TrueBlueNetworkPost[]>(`/api/trueblue/network/posts?limit=${limit}`);
export const getNetworkMetricsOverTime = () => apiFetch<NetworkMetricsOverTime[]>("/api/trueblue/network/metrics-over-time");

// Web Analytics — `site` selects the property ("truebluetv" or "niltv")
export const getGA4Snapshots = (days = 90, site = "truebluetv") => apiFetch<GA4Snapshot[]>(`/api/web-analytics/ga4?days=${days}&site=${site}`);
export const getGSCTotals = (days = 90, site = "truebluetv") => apiFetch<GSCDailyTotal[]>(`/api/web-analytics/gsc?days=${days}&site=${site}`);
export const getGSCQueries = (days = 90, site = "truebluetv") => apiFetch<GSCQuerySnapshot[]>(`/api/web-analytics/gsc/queries?days=${days}&site=${site}`);
export const getGSCPages = (days = 90, site = "truebluetv") => apiFetch<GSCPageSnapshot[]>(`/api/web-analytics/gsc/pages?days=${days}&site=${site}`);
export const getGA4Summary = (site = "truebluetv") => apiFetch<GA4Summary>(`/api/web-analytics/ga4/summary?site=${site}`);
export const getGSCSummary = (site = "truebluetv") => apiFetch<GSCSummary>(`/api/web-analytics/gsc/summary?site=${site}`);

// ── Network Screen (Channel Insights) ─────────────────────────────────────────

import type { NetworkScreenSummary, NetworkScreenTopPost } from "./types";

export const getNetworkScreenSummary = (mode = "month") =>
  apiFetch<NetworkScreenSummary>(`/api/network-screen/summary?mode=${mode}`);
export const getNetworkScreenTopPosts = (limit = 20) =>
  apiFetch<NetworkScreenTopPost[]>(`/api/network-screen/top-posts?limit=${limit}`);

// ── Campus Channels ───────────────────────────────────────────────────────────

import type { CampusChannelsSummary } from "./types";

export const getCampusChannelsSummary = () =>
  apiFetch<CampusChannelsSummary>("/api/campus-channels/summary");

// ── Athlete onboarding (applications) ─────────────────────────────────────────
// Always fresh: staff act on these rows, a 5-minute cache would show stale state.

import type { Application, ApplicationsSummary } from "./types";

async function apiFetchFresh<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: { "X-API-Key": API_KEY }, cache: "no-store" });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const getApplications = (status = "all") =>
  apiFetchFresh<Application[]>(`/api/applications/?status=${encodeURIComponent(status)}`);
export const getApplicationsSummary = () =>
  apiFetchFresh<ApplicationsSummary>("/api/applications/summary");

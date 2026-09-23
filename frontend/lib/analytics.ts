// Pure data-shaping helpers for the Web Analytics views. Extracted from
// WebAnalyticsView so they can be unit-tested without rendering.

import type {
  GA4Snapshot, GSCDailyTotal, GSCQuerySnapshot, GSCPageSnapshot,
  GA4Summary, GSCSummary,
} from "./types";

export const RANGES = [
  { key: "3", label: "3 Days" },
  { key: "7", label: "7 Days" },
  { key: "28", label: "4 Weeks" },
  { key: "all", label: "All Time" },
] as const;

export type RangeKey = (typeof RANGES)[number]["key"];

export function filterByRange<T extends { date: string }>(data: T[], range: RangeKey): T[] {
  if (range === "all") return data;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - Number(range));
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return data.filter((d) => d.date.slice(0, 10) >= cutoffStr);
}

export function computeGA4Summary(snapshots: GA4Snapshot[]): GA4Summary {
  let totalSessions = 0, totalUsers = 0, totalPageviews = 0;
  let bounceSum = 0, engagementSum = 0, bounceCount = 0, engagementCount = 0;

  for (const s of snapshots) {
    totalSessions += s.sessions ?? 0;
    totalUsers += s.total_users ?? 0;
    totalPageviews += s.pageviews ?? 0;
    if (s.bounce_rate != null) { bounceSum += s.bounce_rate; bounceCount++; }
    if (s.engagement_rate != null) { engagementSum += s.engagement_rate; engagementCount++; }
  }

  const sourceMap: Record<string, { sessions: number; users: number }> = {};
  for (const s of snapshots) {
    const key = `${s.source ?? "(direct)"}|${s.medium ?? "(none)"}`;
    if (!sourceMap[key]) sourceMap[key] = { sessions: 0, users: 0 };
    sourceMap[key].sessions += s.sessions ?? 0;
    sourceMap[key].users += s.total_users ?? 0;
  }
  const traffic_sources = Object.entries(sourceMap)
    .map(([key, v]) => {
      const [source, medium] = key.split("|");
      return { source, medium, sessions: v.sessions, users: v.users };
    })
    .sort((a, b) => b.sessions - a.sessions)
    .slice(0, 20);

  return {
    total_sessions: totalSessions,
    total_users: totalUsers,
    total_pageviews: totalPageviews,
    avg_bounce_rate: bounceCount > 0 ? bounceSum / bounceCount : 0,
    avg_engagement_rate: engagementCount > 0 ? engagementSum / engagementCount : 0,
    traffic_sources,
  };
}

export function computeGSCSummary(
  totals: GSCDailyTotal[],
  queries: GSCQuerySnapshot[],
  pages: GSCPageSnapshot[],
): GSCSummary {
  // Accurate aggregates from daily totals (no anonymization)
  let totalClicks = 0, totalImpressions = 0;
  let ctrSum = 0, posSum = 0, ctrCount = 0, posCount = 0;

  for (const t of totals) {
    totalClicks += t.clicks ?? 0;
    totalImpressions += t.impressions ?? 0;
    if (t.ctr != null) { ctrSum += t.ctr; ctrCount++; }
    if (t.position != null) { posSum += t.position; posCount++; }
  }

  // Top queries from query-specific data
  const queryMap: Record<string, { clicks: number; impressions: number; ctrSum: number; posSum: number; count: number }> = {};
  for (const s of queries) {
    if (!queryMap[s.query]) queryMap[s.query] = { clicks: 0, impressions: 0, ctrSum: 0, posSum: 0, count: 0 };
    queryMap[s.query].clicks += s.clicks ?? 0;
    queryMap[s.query].impressions += s.impressions ?? 0;
    if (s.ctr != null) { queryMap[s.query].ctrSum += s.ctr; queryMap[s.query].count++; }
    if (s.position != null) queryMap[s.query].posSum += s.position;
  }
  const top_queries = Object.entries(queryMap)
    .map(([query, v]) => ({
      query,
      clicks: v.clicks,
      impressions: v.impressions,
      avg_ctr: v.count > 0 ? v.ctrSum / v.count : 0,
      avg_position: v.count > 0 ? v.posSum / v.count : 0,
    }))
    .sort((a, b) => b.clicks - a.clicks)
    .slice(0, 25);

  // Top pages from page-specific data
  const pageMap: Record<string, { clicks: number; impressions: number; ctrSum: number; posSum: number; count: number }> = {};
  for (const s of pages) {
    if (!pageMap[s.page]) pageMap[s.page] = { clicks: 0, impressions: 0, ctrSum: 0, posSum: 0, count: 0 };
    pageMap[s.page].clicks += s.clicks ?? 0;
    pageMap[s.page].impressions += s.impressions ?? 0;
    if (s.ctr != null) { pageMap[s.page].ctrSum += s.ctr; pageMap[s.page].count++; }
    if (s.position != null) pageMap[s.page].posSum += s.position;
  }
  const top_pages = Object.entries(pageMap)
    .map(([page, v]) => ({
      page,
      clicks: v.clicks,
      impressions: v.impressions,
      avg_ctr: v.count > 0 ? v.ctrSum / v.count : 0,
      avg_position: v.count > 0 ? v.posSum / v.count : 0,
    }))
    .sort((a, b) => b.clicks - a.clicks)
    .slice(0, 25);

  return {
    total_clicks: totalClicks,
    total_impressions: totalImpressions,
    avg_ctr: ctrCount > 0 ? ctrSum / ctrCount : 0,
    avg_position: posCount > 0 ? posSum / posCount : 0,
    top_queries,
    top_pages,
  };
}

import { describe, it, expect } from "vitest";
import { filterByRange, computeGA4Summary, computeGSCSummary } from "./analytics";
import type {
  GA4Snapshot, GSCDailyTotal, GSCQuerySnapshot, GSCPageSnapshot,
} from "./types";

// Minimal builders — cast away the full shape, override what each test needs.
const ga4 = (p: Partial<GA4Snapshot>): GA4Snapshot =>
  ({ id: 0, date: "2026-06-01", pulled_at: "2026-06-01", sessions: 0, total_users: 0,
     pageviews: 0, bounce_rate: 0, engagement_rate: 0, source: null, medium: null, ...p } as GA4Snapshot);
const gscTotal = (p: Partial<GSCDailyTotal>): GSCDailyTotal =>
  ({ id: 0, date: "2026-06-01", clicks: 0, impressions: 0, ctr: 0, position: 0, ...p } as GSCDailyTotal);
const gscQuery = (p: Partial<GSCQuerySnapshot>): GSCQuerySnapshot =>
  ({ id: 0, date: "2026-06-01", query: "", clicks: 0, impressions: 0, ctr: 0, position: 0, ...p } as GSCQuerySnapshot);
const gscPage = (p: Partial<GSCPageSnapshot>): GSCPageSnapshot =>
  ({ id: 0, date: "2026-06-01", page: "", clicks: 0, impressions: 0, ctr: 0, position: 0, ...p } as GSCPageSnapshot);

describe("filterByRange", () => {
  it("returns everything for 'all'", () => {
    const rows = [{ date: "2000-01-01" }, { date: "2026-06-01" }];
    expect(filterByRange(rows, "all")).toHaveLength(2);
  });

  it("drops rows older than the window", () => {
    const today = new Date().toISOString().slice(0, 10);
    const out = filterByRange([{ date: "2000-01-01" }, { date: today }], "7");
    expect(out).toEqual([{ date: today }]);
  });
});

describe("computeGA4Summary", () => {
  it("sums totals, averages rates, and buckets sources", () => {
    const s = computeGA4Summary([
      ga4({ sessions: 100, total_users: 80, pageviews: 200, bounce_rate: 0.4, engagement_rate: 0.6, source: "google", medium: "organic" }),
      ga4({ sessions: 50, total_users: 40, pageviews: 90, bounce_rate: 0.6, engagement_rate: 0.4, source: "google", medium: "organic" }),
    ]);
    expect(s.total_sessions).toBe(150);
    expect(s.total_users).toBe(120);
    expect(s.total_pageviews).toBe(290);
    expect(s.avg_bounce_rate).toBeCloseTo(0.5);
    expect(s.avg_engagement_rate).toBeCloseTo(0.5);
    expect(s.traffic_sources).toHaveLength(1);
    expect(s.traffic_sources[0]).toMatchObject({ source: "google", medium: "organic", sessions: 150, users: 120 });
  });

  it("handles empty input without NaN", () => {
    const s = computeGA4Summary([]);
    expect(s.total_sessions).toBe(0);
    expect(s.avg_bounce_rate).toBe(0);
    expect(s.traffic_sources).toHaveLength(0);
  });
});

describe("computeGSCSummary", () => {
  it("aggregates totals and ranks top queries/pages by clicks", () => {
    const s = computeGSCSummary(
      [gscTotal({ clicks: 30, impressions: 300, ctr: 0.1, position: 3 }),
       gscTotal({ clicks: 20, impressions: 200, ctr: 0.1, position: 5 })],
      [gscQuery({ query: "duke nil", clicks: 25, impressions: 250 }),
       gscQuery({ query: "trueblue", clicks: 5, impressions: 50 })],
      [gscPage({ page: "/a", clicks: 40, impressions: 400 }),
       gscPage({ page: "/b", clicks: 10, impressions: 100 })],
    );
    expect(s.total_clicks).toBe(50);
    expect(s.total_impressions).toBe(500);
    expect(s.avg_position).toBeCloseTo(4);
    expect(s.top_queries[0].query).toBe("duke nil");
    expect(s.top_pages[0].page).toBe("/a");
  });
});

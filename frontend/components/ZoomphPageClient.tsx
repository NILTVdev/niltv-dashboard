"use client";

import { useState, useMemo, useEffect } from "react";
import type { ZoomphPost, ZoomphSummary, ZoomphDailyImpressions } from "@/lib/types";
import ZoomphKPIs from "./ZoomphKPIs";
import { PlatformBreakdown, ImpressionsTimeSeries } from "./ZoomphCharts";
import ZoomphTable from "./ZoomphTable";

const API = "/api/proxy";

const RANGES = [
  { key: "30", label: "30 Days" },
  { key: "90", label: "90 Days" },
  { key: "all", label: "All Time" },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

/** Map Zoomph author handles (lowercased) → readable sport / account names. */
const HANDLE_TO_SPORT: Record<string, string> = {
  dukefootball: "Football",
  dukefb: "Football",
  dukembb: "Men's Basketball",
  dukeathletics: "Athletics",
  dukewsoc: "Women's Soccer",
  dukesoftball: "Softball",
  dukewbb: "Women's Basketball",
  dukebase: "Baseball",
  duketfxc: "Track & Field",
  dukemsoc: "Men's Soccer",
  dukewgolf: "Women's Golf",
  dukemgolf: "Men's Golf",
  dukewlax: "Women's Lacrosse",
  dukerow: "Rowing",
  dukemlax: "Men's Lacrosse",
  dukevb: "Volleyball",
  dukewres: "Wrestling",
  dukewten: "Women's Tennis",
  dukeswimdive: "Swim and Dive",
  dukemten: "Men's Tennis",
  dukefh: "Field Hockey",
  dukefen: "Fencing",
};

/** Resolve a raw author handle to a readable sport name. */
function resolveAccount(author: string | null, url?: string | null): string {
  if (author) {
    const key = author.replace(/^@/, "").trim().toLowerCase();
    if (HANDLE_TO_SPORT[key]) return HANDLE_TO_SPORT[key];
    return author;
  }
  if (!url) return "Unknown";
  try {
    const { hostname, pathname } = new URL(url);
    if (/(?:twitter|x|instagram|facebook|tiktok)\.com$/i.test(hostname)) {
      const seg = pathname.split("/").filter(Boolean)[0];
      if (seg) {
        const key = seg.toLowerCase();
        return HANDLE_TO_SPORT[key] ?? seg;
      }
    }
  } catch { /* ignore */ }
  return "Unknown";
}

/** Build a reverse lookup: sport name → list of raw author handles. */
function buildSportToHandles(authors: string[]): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  for (const handle of authors) {
    const sport = resolveAccount(handle);
    if (!map[sport]) map[sport] = [];
    if (!map[sport].includes(handle)) map[sport].push(handle);
  }
  return map;
}

/** Compute start_date string for a given range key. */
function rangeToStartDate(range: RangeKey): string | undefined {
  if (range === "all") return undefined;
  const d = new Date();
  d.setDate(d.getDate() - Number(range));
  return d.toISOString().slice(0, 10);
}

interface Props {
  posts: ZoomphPost[];
  summary: ZoomphSummary[];
  authors: string[];
  impressionsByDay: ZoomphDailyImpressions[];
}

export default function ZoomphPageClient({ posts, summary, authors, impressionsByDay }: Props) {
  const [account, setAccount] = useState("all");
  const [range, setRange] = useState<RangeKey>("all");

  // Server-side summary for KPIs — updated when account/range filter changes
  const [kpiSummary, setKpiSummary] = useState<ZoomphSummary[]>(summary);
  const [timeSeriesData, setTimeSeriesData] = useState<ZoomphDailyImpressions[]>(impressionsByDay);
  const [tablePosts, setTablePosts] = useState<ZoomphPost[]>(posts);

  const sportToHandles = useMemo(() => buildSportToHandles(authors), [authors]);
  const accountNames = useMemo(() => [...new Set(Object.keys(sportToHandles))].sort(), [sportToHandles]);

  // Re-fetch all data when account or range changes
  useEffect(() => {
    const startDate = rangeToStartDate(range);
    const handles = account === "all" ? [] : (sportToHandles[account] ?? []);

    // Build query string helper
    const qs = (extra?: Record<string, string>) => {
      const p = new URLSearchParams();
      if (startDate) p.set("start_date", startDate);
      if (extra) Object.entries(extra).forEach(([k, v]) => p.set(k, v));
      return p.toString() ? `?${p}` : "";
    };

    // Fetch summary
    if (account === "all") {
      fetch(`${API}/api/zoomph/summary${qs()}`)
        .then((r) => r.json() as Promise<ZoomphSummary[]>)
        .then(setKpiSummary);
    } else {
      Promise.all(
        handles.map((h) =>
          fetch(`${API}/api/zoomph/summary${qs({ author: h })}`)
            .then((r) => r.json() as Promise<ZoomphSummary[]>)
        )
      ).then((results) => {
        const byPlatform: Record<string, ZoomphSummary> = {};
        for (const summaries of results) {
          for (const s of summaries) {
            const p = s.platform ?? "Unknown";
            if (!byPlatform[p]) {
              byPlatform[p] = { platform: p, post_count: 0, total_engagement: 0, total_impressions: 0, total_likes: 0, total_bev: 0 };
            }
            byPlatform[p].post_count += s.post_count;
            byPlatform[p].total_engagement += s.total_engagement;
            byPlatform[p].total_impressions += s.total_impressions;
            byPlatform[p].total_likes += s.total_likes;
            byPlatform[p].total_bev += s.total_bev;
          }
        }
        setKpiSummary(Object.values(byPlatform));
      });
    }

    // Fetch impressions time series
    if (account === "all") {
      fetch(`${API}/api/zoomph/impressions-by-day${qs()}`)
        .then((r) => r.json() as Promise<ZoomphDailyImpressions[]>)
        .then(setTimeSeriesData);
    } else {
      Promise.all(
        handles.map((h) =>
          fetch(`${API}/api/zoomph/impressions-by-day${qs({ author: h })}`)
            .then((r) => r.json() as Promise<ZoomphDailyImpressions[]>)
        )
      ).then((results) => {
        const byDay: Record<string, number> = {};
        for (const days of results) {
          for (const d of days) {
            byDay[d.date] = (byDay[d.date] ?? 0) + d.impressions;
          }
        }
        setTimeSeriesData(
          Object.entries(byDay).map(([date, impressions]) => ({ date, impressions }))
        );
      });
    }

    // Fetch posts for table
    if (account === "all") {
      fetch(`${API}/api/zoomph/${qs({ limit: "500" })}`)
        .then((r) => r.json() as Promise<ZoomphPost[]>)
        .then(setTablePosts);
    } else {
      Promise.all(
        handles.map((h) =>
          fetch(`${API}/api/zoomph/${qs({ limit: "500", author: h })}`)
            .then((r) => r.json() as Promise<ZoomphPost[]>)
        )
      ).then((results) => {
        const merged = results.flat().sort((a, b) => {
          const da = a.posted_at ?? "";
          const db = b.posted_at ?? "";
          return db.localeCompare(da);
        });
        setTablePosts(merged.slice(0, 500));
      });
    }
  }, [account, range, sportToHandles]);

  const platforms = useMemo(
    () => [...new Set(tablePosts.map((p) => p.platform).filter(Boolean) as string[])].sort(),
    [tablePosts]
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a] mb-1">Duke Owned</h1>
          <p className="text-sm text-[#64748b]">
            Impressions, engagement, and social valuation for Duke-owned accounts.
          </p>
        </div>
        <div className="flex gap-3">
          <div className="flex gap-1 bg-[#f1f5f9] rounded-lg p-1">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setRange(r.key)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  range === r.key
                    ? "bg-white text-[var(--brand)] shadow-sm"
                    : "text-[#64748b] hover:text-[#0f172a]"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <select
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            className="px-4 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)] font-medium"
          >
            <option value="all">All Sports</option>
            {accountNames.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>
      </div>

      {/* KPIs use server-side summary (all posts in range, not just 500) */}
      <ZoomphKPIs summary={kpiSummary} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
          <h2 className="text-sm font-semibold text-[#0f172a] mb-4">Impressions by Platform</h2>
          <PlatformBreakdown summary={kpiSummary} />
        </div>
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
          <h2 className="text-sm font-semibold text-[#0f172a] mb-4">Impressions Over Time</h2>
          <ImpressionsTimeSeries data={timeSeriesData} />
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h2 className="text-sm font-semibold text-[#0f172a] mb-4">Posts</h2>
        <ZoomphTable posts={tablePosts} platforms={platforms} hideAccountFilter />
      </div>
    </div>
  );
}

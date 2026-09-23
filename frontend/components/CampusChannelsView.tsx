"use client";

import { useMemo, useState } from "react";
import { ArrowUpDown, Eye, FileText, Info, TrendingUp, TriangleAlert, Users } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  CampusChannelsSummary,
  CampusChannelSummary,
  CampusChannelViewGrowth,
  CampusChannelWindowStats,
} from "@/lib/types";
import { fmt, fmtDate } from "@/lib/utils";

const GOLD = "#C9A227";

type WindowKey = "last_month" | "current_month" | "last_30_days" | "all_time";
type SortKey = WindowKey | "channel";

// Views written by Business Discovery or a public grid snapshot are a play
// count, not the Graph/Business Suite views metric — worth flagging in the UI.
const LOW_CONFIDENCE_SOURCES = ["bd", "public", "unknown"];
const CHANNEL_COLORS: Record<string, string> = {
  truebluetv: "#003087",
  chapelhilltv: "#7BAFD4",
  redpacktv: "#CC0000",
  starkvilletv: "#5D1725",
  goldendometv: "#C99700",
  dorecitytv: "#866D4B",
  collegestationtv: "#500000",
  brazostv: "#154734",
};

function stats(channel: CampusChannelSummary, key: WindowKey): CampusChannelWindowStats {
  return channel[key];
}

/** Share of view-bearing posts whose number came from a low-confidence source. */
function lowConfidenceShare(channel: CampusChannelSummary): number | null {
  const entries = Object.entries(channel.views_by_source);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (!total) return null;
  const low = entries
    .filter(([source]) => LOW_CONFIDENCE_SOURCES.includes(source))
    .reduce((sum, [, count]) => sum + count, 0);
  return low / total;
}

function rangeLabel(start: string | undefined, end: string | undefined): string {
  if (!start || !end) return "";
  const from = new Date(start);
  // `end` is exclusive; step back a day so the label reads as an inclusive range.
  const to = new Date(new Date(end).getTime() - 86_400_000);
  const sameMonth = from.getUTCMonth() === to.getUTCMonth() && from.getUTCFullYear() === to.getUTCFullYear();
  const monthName = (d: Date) => d.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });

  if (sameMonth && from.getUTCDate() === 1 && to.getUTCDate() >= 28) {
    return from.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  }
  if (sameMonth) {
    return `${monthName(from)} ${from.getUTCDate()}–${to.getUTCDate()}`;
  }
  return `${monthName(from)} ${from.getUTCDate()} – ${monthName(to)} ${to.getUTCDate()}`;
}

/* ── Cells ────────────────────────────────────────────────────────────── */

function ViewsCell({ data }: { data: CampusChannelWindowStats }) {
  const missing = data.posts > 0 && data.posts_with_views < data.posts;
  return (
    <td className="py-3 pr-4 text-right align-top">
      <div className="font-semibold text-[#0f172a] tabular-nums">
        {data.views == null ? "—" : fmt(data.views)}
      </div>
      <div className="text-[11px] text-[#94a3b8] tabular-nums">
        {data.posts === 0
          ? "no posts"
          : `${data.posts} post${data.posts === 1 ? "" : "s"}${missing ? ` · ${data.posts_with_views} w/ views` : ""}`}
      </div>
    </td>
  );
}

function GrowthValue({ data }: { data: CampusChannelViewGrowth }) {
  const eligible = data.posts_measured + data.posts_missing_baseline;
  return (
    <div className="text-right">
      <div className="font-semibold text-[#0f172a] tabular-nums">
        {data.views_gained == null ? "—" : `+${fmt(data.views_gained)}`}
      </div>
      <div className="text-[10px] text-[#94a3b8] tabular-nums">
        {eligible === 0 ? "no eligible posts" : `${data.coverage_pct}% coverage`}
      </div>
    </div>
  );
}

const EMPTY_GROWTH: CampusChannelViewGrowth = {
  start: "",
  end: "",
  views_gained: null,
  posts_measured: 0,
  posts_missing_baseline: 0,
  regressed_posts: 0,
  coverage_pct: 0,
};

function monthGrowthLabel(start: string): string {
  return new Date(start).toLocaleDateString("en-US", {
    month: "short",
    year: "2-digit",
    timeZone: "UTC",
  });
}

function SortHeader({
  label,
  subLabel,
  field,
  activeField,
  dir,
  onSort,
  align = "right",
}: {
  label: string;
  subLabel?: string;
  field: SortKey;
  activeField: SortKey;
  dir: "asc" | "desc";
  onSort: (field: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = activeField === field;
  return (
    <th className={`py-2 pr-4 font-medium ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        onClick={() => onSort(field)}
        aria-label={`Sort by ${label}`}
        className={`inline-flex items-center gap-1 ${align === "right" ? "flex-row-reverse" : ""} hover:text-[#0f172a] transition-colors ${
          active ? "text-[#0f172a]" : "text-[#64748b]"
        }`}
      >
        <ArrowUpDown size={11} className={active ? "opacity-100" : "opacity-40"} />
        <span className="flex flex-col leading-tight">
          <span>{label}</span>
          {subLabel && <span className="text-[10px] font-normal text-[#94a3b8]">{subLabel}</span>}
        </span>
      </button>
      {active && <span className="sr-only">{dir === "asc" ? "ascending" : "descending"}</span>}
    </th>
  );
}

/* ── KPI banner ───────────────────────────────────────────────────────── */

function Banner({ channels }: { channels: CampusChannelSummary[] }) {
  const allTimeViews = channels.reduce((sum, c) => sum + (c.all_time.views ?? 0), 0);
  const allTimePosts = channels.reduce((sum, c) => sum + c.all_time.posts, 0);
  const monthViews = channels.reduce((sum, c) => sum + (c.current_month.views ?? 0), 0);
  const withData = channels.filter((c) => c.all_time.posts > 0).length;

  const cards = [
    { label: "Channels with Data", value: `${withData} / ${channels.length}`, icon: <Users size={14} /> },
    { label: "Views This Month", value: fmt(monthViews), icon: <Eye size={14} /> },
    { label: "All-Time Views", value: fmt(allTimeViews), icon: <Eye size={14} /> },
    { label: "All-Time Posts", value: fmt(allTimePosts), icon: <FileText size={14} /> },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {cards.map(({ label, value, icon }) => (
        <div key={label} className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex flex-col gap-1">
          <span className="flex items-center gap-1.5 text-xs font-medium text-[#64748b]">
            {icon}
            {label}
          </span>
          <span className="text-2xl font-bold text-[#0f172a]">{value}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Root ─────────────────────────────────────────────────────────────── */

export default function CampusChannelsView({ summary }: { summary: CampusChannelsSummary | null }) {
  const [sortField, setSortField] = useState<SortKey>("all_time");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    if (!summary) return [];
    const rows = [...summary.channels];
    rows.sort((a, b) => {
      if (sortField === "channel") {
        const cmp = a.label.localeCompare(b.label);
        return sortDir === "asc" ? cmp : -cmp;
      }
      // Null views sort as -1 so "no data" always lands below a real zero.
      const av = stats(a, sortField).views ?? -1;
      const bv = stats(b, sortField).views ?? -1;
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return rows;
  }, [summary, sortField, sortDir]);

  const monthlyChartData = useMemo(() => {
    if (!summary?.channels.length) return [];
    return (summary.channels[0].monthly_growth ?? []).map((period, index) => {
      const point: Record<string, string | number | null> = {
        period: monthGrowthLabel(period.start),
      };
      for (const channel of summary.channels) {
        point[channel.channel] = channel.monthly_growth?.[index]?.views_gained ?? null;
      }
      return point;
    });
  }, [summary]);

  const weeklyChartData = useMemo(() => {
    if (!summary) return [];
    return summary.channels.map((channel) => ({
      channel: channel.label,
      key: channel.channel,
      views: channel.last_7_days_growth?.views_gained ?? null,
    }));
  }, [summary]);

  if (!summary) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-10">
        <p className="text-sm text-[#94a3b8]">
          Could not load Campus Channels — check that the API is reachable.
        </p>
      </main>
    );
  }

  function toggleSort(field: SortKey) {
    if (field === sortField) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir(field === "channel" ? "asc" : "desc");
    }
  }

  const lastMonthLabel = rangeLabel(summary.windows.last_month?.start, summary.windows.last_month?.end);
  const currentMonthLabel = rangeLabel(summary.windows.current_month?.start, summary.windows.current_month?.end);
  const last30Label = rangeLabel(summary.windows.last_30_days?.start, summary.windows.last_30_days?.end);

  return (
    <main className="max-w-6xl mx-auto px-4 py-8 flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold text-[#0f172a]">Campus Channels</h1>
        <p className="text-sm text-[#64748b] mt-1">
          Per-channel Instagram performance across the NIL TV campus network
        </p>
      </div>

      <Banner channels={summary.channels} />

      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
          <h2 className="text-sm font-semibold text-[#0f172a]">Channel Performance</h2>
          <span className="text-xs text-[#94a3b8]">Click any column to sort</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[46rem]">
            <thead>
              <tr className="border-b border-[#e2e8f0] text-[#64748b]">
                <SortHeader
                  label="Channel"
                  field="channel"
                  activeField={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                  align="left"
                />
                <SortHeader
                  label="Last Month"
                  subLabel={lastMonthLabel}
                  field="last_month"
                  activeField={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <SortHeader
                  label="This Month"
                  subLabel={currentMonthLabel}
                  field="current_month"
                  activeField={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <SortHeader
                  label="Last 30 Days"
                  subLabel={last30Label}
                  field="last_30_days"
                  activeField={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <SortHeader
                  label="All Time"
                  field="all_time"
                  activeField={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <th className="py-2 font-medium text-right">Latest Post</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((channel) => {
                const lowShare = lowConfidenceShare(channel);
                const flagged = lowShare != null && lowShare >= 0.5;
                return (
                  <tr key={channel.channel} className="border-b border-[#f1f5f9] last:border-0 hover:bg-[#fdf9ee]">
                    <td className="py-3 pr-4 align-top">
                      <div className="font-medium text-[#0f172a] flex items-center gap-1.5">
                        {channel.label}
                        {flagged && (
                          <span
                            title="Most views for this channel come from Business Discovery or a public grid snapshot, which report a play count rather than the Graph/Business Suite views metric."
                            className="inline-flex items-center"
                          >
                            <TriangleAlert size={12} className="text-[#d97706]" />
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-[#94a3b8]">@{channel.channel}</div>
                    </td>
                    <ViewsCell data={channel.last_month} />
                    <ViewsCell data={channel.current_month} />
                    <ViewsCell data={channel.last_30_days} />
                    <ViewsCell data={channel.all_time} />
                    <td className="py-3 text-right align-top text-xs text-[#64748b] whitespace-nowrap">
                      {channel.latest_post_at ? fmtDate(channel.latest_post_at) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-5 pt-4 border-t border-[#f1f5f9] flex flex-col gap-2">
          <div className="flex items-start gap-1.5 text-xs text-[#64748b]">
            <Info size={12} className="mt-0.5 shrink-0" style={{ color: GOLD }} />
            <span>
              Every window counts views on posts <strong>published</strong> in that window — not views accrued
              during it. A post published in July that gained views in August counts toward July.
            </span>
          </div>
          <div className="flex items-start gap-1.5 text-xs text-[#64748b]">
            <TriangleAlert size={12} className="mt-0.5 shrink-0 text-[#d97706]" />
            <span>
              TrueBlueTV runs on Business Discovery, which cannot read views — its figures depend on CSV uploads
              and may lag. Flagged rows draw most of their views from lower-confidence sources.
            </span>
          </div>
          <div className="text-[11px] text-[#94a3b8]">
            Dashes mean no view data was ingested for that window, which is different from zero views.
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
        <div className="flex items-start justify-between flex-wrap gap-3 mb-5">
          <div>
            <h2 className="text-sm font-semibold text-[#0f172a] flex items-center gap-1.5">
              <TrendingUp size={15} style={{ color: GOLD }} />
              Views Gained by Month
            </h2>
            <p className="text-xs text-[#64748b] mt-1">
              Change in total post views between each month&apos;s opening and closing snapshots, including older posts that kept gaining views.
            </p>
          </div>
          <span className="text-[11px] text-[#94a3b8]">Latest 6 months · current month is month-to-date</span>
        </div>

        <div className="h-80 mb-6">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={monthlyChartData} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#64748b" }} />
              <YAxis tickFormatter={(value) => fmt(Number(value))} tick={{ fontSize: 11, fill: "#64748b" }} width={52} />
              <Tooltip formatter={(value) => [value == null ? "—" : fmt(Number(value)), "Views gained"]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {summary.channels.map((channel) => (
                <Line
                  key={channel.channel}
                  type="monotone"
                  dataKey={channel.channel}
                  name={channel.label}
                  stroke={CHANNEL_COLORS[channel.channel] ?? GOLD}
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[52rem]">
            <thead>
              <tr className="border-b border-[#e2e8f0] text-[#64748b]">
                <th className="py-2 pr-4 text-left font-medium">Channel</th>
                <th className="py-2 pr-4 text-right font-medium">
                  <span className="flex flex-col leading-tight">
                    <span>Last 30 Days</span>
                    <span className="text-[10px] font-normal text-[#94a3b8]">rolling delta</span>
                  </span>
                </th>
                {(summary.channels[0]?.monthly_growth ?? []).map((period) => (
                  <th key={period.start} className="py-2 pr-4 text-right font-medium">
                    {monthGrowthLabel(period.start)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {summary.channels.map((channel) => (
                <tr key={channel.channel} className="border-b border-[#f1f5f9] last:border-0">
                  <td className="py-3 pr-4 font-medium text-[#0f172a]">{channel.label}</td>
                  <td className="py-3 pr-4 align-top">
                    <GrowthValue data={channel.last_30_days_growth ?? EMPTY_GROWTH} />
                  </td>
                  {(channel.monthly_growth ?? []).map((period) => (
                    <td key={period.start} className="py-3 pr-4 align-top">
                      <GrowthValue data={period} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
        <div className="mb-5">
          <h2 className="text-sm font-semibold text-[#0f172a] flex items-center gap-1.5">
            <TrendingUp size={15} style={{ color: GOLD }} />
            Views Gained · Last 7 Days
          </h2>
          <p className="text-xs text-[#64748b] mt-1">
            Snapshot-to-current growth across every tracked post, not only posts published this week.
          </p>
        </div>

        <div className="grid lg:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.65fr)] gap-6 items-start">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={weeklyChartData} margin={{ top: 8, right: 12, left: 4, bottom: 52 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="channel" angle={-35} textAnchor="end" interval={0} tick={{ fontSize: 10, fill: "#64748b" }} />
                <YAxis tickFormatter={(value) => fmt(Number(value))} tick={{ fontSize: 11, fill: "#64748b" }} width={52} />
                <Tooltip formatter={(value) => [value == null ? "—" : fmt(Number(value)), "Views gained"]} />
                <Bar dataKey="views" radius={[3, 3, 0, 0]}>
                  {weeklyChartData.map((point) => (
                    <Cell key={point.key} fill={CHANNEL_COLORS[point.key] ?? GOLD} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="divide-y divide-[#f1f5f9]">
            {summary.channels.map((channel) => (
              <div key={channel.channel} className="grid grid-cols-[1fr_auto] gap-3 py-2.5 first:pt-0">
                <div>
                  <div className="text-sm font-medium text-[#0f172a]">{channel.label}</div>
                  <div className="text-[10px] text-[#94a3b8]">
                    {channel.last_7_days_growth?.posts_measured ?? 0} measured · {channel.last_7_days_growth?.coverage_pct ?? 0}% coverage
                  </div>
                </div>
                <GrowthValue data={channel.last_7_days_growth ?? EMPTY_GROWTH} />
              </div>
            ))}
          </div>
        </div>

        <div className="mt-5 pt-4 border-t border-[#f1f5f9] text-xs text-[#64748b] flex items-start gap-1.5">
          <Info size={12} className="mt-0.5 shrink-0" style={{ color: GOLD }} />
          <span>
            Growth uses the latest available snapshot at each boundary. Older posts without a start snapshot are excluded and lower coverage is shown; negative source regressions are counted but contribute zero growth.
          </span>
        </div>
      </div>
    </main>
  );
}

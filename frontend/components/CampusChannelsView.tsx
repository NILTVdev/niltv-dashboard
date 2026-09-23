"use client";

import { useMemo, useState } from "react";
import { ArrowUpDown, Eye, FileText, Info, TriangleAlert, Users } from "lucide-react";
import type {
  CampusChannelsSummary,
  CampusChannelSummary,
  CampusChannelWindowStats,
} from "@/lib/types";
import { fmt, fmtDate } from "@/lib/utils";

const GOLD = "#C9A227";

type WindowKey = "last_month" | "current_month" | "last_30_days" | "all_time";
type SortKey = WindowKey | "channel";

// Views written by Business Discovery or a public grid snapshot are a play
// count, not the Graph/Business Suite views metric — worth flagging in the UI.
const LOW_CONFIDENCE_SOURCES = ["bd", "public", "unknown"];

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
    </main>
  );
}

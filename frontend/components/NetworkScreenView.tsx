"use client";

import { useState } from "react";
import {
  Users, Eye, FileText, TrendingUp, Heart, MessageCircle,
  Share2, Bookmark, ExternalLink, TriangleAlert, Info,
} from "lucide-react";
import type {
  NetworkScreenSummary,
  NetworkScreenMonthStats,
  NetworkScreenTopPost,
  NetworkScreenRatios,
  NetworkScreenFormatStats,
  NetworkScreenWeeklyComparison,
} from "@/lib/types";
import { FORMAT_LABELS, formatLabel } from "@/lib/formatLabels";
import { fmt, fmtDate } from "@/lib/utils";

const PLATFORMS = ["instagram", "facebook", "youtube", "tiktok", "snapchat", "linkedin"] as const;
const PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  youtube: "YouTube",
  tiktok: "TikTok",
  snapchat: "Snapchat",
  linkedin: "LinkedIn",
};

/* ── Shared primitives ────────────────────────────────────────────────── */

function val(n: number | null | undefined, suffix = ""): string {
  if (n == null) return "—";
  return fmt(n) + suffix;
}

function delta(n: number | null | undefined): { text: string; color: string } {
  if (n == null) return { text: "—", color: "#94a3b8" };
  const sign = n > 0 ? "+" : "";
  const color = n > 0 ? "#16a34a" : n < 0 ? "#dc2626" : "#64748b";
  return { text: `${sign}${fmt(n)}`, color };
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
      <h2 className="text-sm font-semibold text-[#0f172a] mb-4">{title}</h2>
      {children}
    </div>
  );
}

/* ── Ratio card (prominent, gold-accented) ────────────────────────────── */

function RatioCard({
  label,
  value,
  description,
}: {
  label: string;
  value: string;
  description: string;
}) {
  return (
    <div className="bg-white rounded-2xl border-2 border-[#C9A227] shadow-sm p-5 flex flex-col gap-1">
      <span className="text-xs font-semibold text-[#C9A227] uppercase tracking-wide">{label}</span>
      <span className="text-3xl font-bold text-[#0f172a]">{value}</span>
      <span className="text-xs text-[#64748b]">{description}</span>
    </div>
  );
}

/* ── Month comparison row ─────────────────────────────────────────────── */

function CompareRow({
  label,
  current,
  prior,
  isPercent = false,
}: {
  label: string;
  current: number | null;
  prior: number | null;
  isPercent?: boolean;
}) {
  const suffix = isPercent ? "%" : "";
  const d = delta(current != null && prior != null ? current - prior : null);
  return (
    <div className="grid grid-cols-[minmax(12rem,1fr)_7rem_7rem_5rem] gap-2 items-center py-2 border-b border-[#f1f5f9] last:border-0 text-sm">
      <span className="text-[#64748b]">{label}</span>
      <span className="font-semibold text-[#0f172a] text-right">
        {current != null ? `${fmt(current)}${suffix}` : "—"}
      </span>
      <span className="text-right text-[#64748b]">
        {prior != null ? `${fmt(prior)}${suffix}` : "—"}
      </span>
      <span className="text-right font-medium text-xs" style={{ color: d.color }}>
        {d.text}
      </span>
    </div>
  );
}

function weekRangeLabel(start: string, end: string): string {
  const first = new Date(start);
  const last = new Date(new Date(end).getTime() - 86_400_000);
  const format = (date: Date) => date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  return `${format(first)}–${format(last)}`;
}

function WeeklyPulse({ weekly }: { weekly: NetworkScreenWeeklyComparison }) {
  const currentLabel = `Last 7 days · ${weekRangeLabel(weekly.current.start, weekly.current.end)}`;
  const previousLabel = `Previous 7 · ${weekRangeLabel(weekly.previous.start, weekly.previous.end)}`;
  return (
    <Section title="Weekly Pulse">
      <p className="text-xs text-[#64748b] mb-4">
        Always compares the latest seven calendar days, including today, with the seven days immediately before them. This does not change with the month comparison selector.
      </p>
      <div className="overflow-x-auto">
        <div className="min-w-[31rem]">
          <div className="grid grid-cols-[minmax(12rem,1fr)_7rem_7rem_5rem] gap-2 text-xs text-[#94a3b8] mb-1">
            <span />
            <span className="text-right font-medium text-[#475569]">{currentLabel}</span>
            <span className="text-right">{previousLabel}</span>
            <span className="text-right">Change</span>
          </div>
          <CompareRow label="New Followers" current={weekly.current.new_followers} prior={weekly.previous.new_followers} />
          <CompareRow label="Posts Published" current={weekly.current.posts} prior={weekly.previous.posts} />
          <CompareRow label="Views on Published Posts" current={weekly.current.views} prior={weekly.previous.views} />
        </div>
      </div>
    </Section>
  );
}

/* ── Format breakdown table ───────────────────────────────────────────── */

function FormatTable({ breakdown }: { breakdown: Record<string, NetworkScreenFormatStats> }) {
  // Every bucket, untyped included, so the Posts column sums to Posts Published.
  const rows = Object.entries(breakdown)
    .sort((a, b) => b[1].total_views - a[1].total_views);

  if (!rows.length) {
    return <p className="text-sm text-[#94a3b8]">No posts this month.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
            <th className="py-2 pr-4 font-medium">Format</th>
            <th className="py-2 pr-4 font-medium text-right">Posts</th>
            <th className="py-2 pr-4 font-medium text-right">Total Views</th>
            <th className="py-2 pr-4 font-medium text-right">Avg Views</th>
            <th className="py-2 font-medium text-right">Eng. Rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, s]) => (
            <tr key={key} className="border-b border-[#f1f5f9] last:border-0">
              <td className="py-2 pr-4 font-medium text-[#0f172a]">
                <span className="inline-block text-xs px-2 py-0.5 rounded bg-[#f1f5f9] text-[#475569]">
                  {FORMAT_LABELS[key] ?? key}
                </span>
              </td>
              <td className="py-2 pr-4 text-right">{s.posts}</td>
              <td className="py-2 pr-4 text-right">{fmt(s.total_views)}</td>
              <td className="py-2 pr-4 text-right">{fmt(Math.round(s.avg_views))}</td>
              <td className="py-2 text-right">
                {s.engagement_rate != null ? `${s.engagement_rate}%` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Top posts table ──────────────────────────────────────────────────── */

function TopPostsTable({ posts }: { posts: NetworkScreenTopPost[] }) {
  if (!posts.length) {
    return <p className="text-sm text-[#94a3b8]">No posts with view data yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
            <th className="py-2 pr-3 font-medium">Date</th>
            <th className="py-2 pr-3 font-medium">Format</th>
            <th className="py-2 pr-3 font-medium text-right">Views</th>
            <th className="py-2 pr-3 font-medium text-right">
              <Heart size={12} className="inline mr-0.5" />Likes
            </th>
            <th className="py-2 pr-3 font-medium text-right">
              <MessageCircle size={12} className="inline mr-0.5" />Cmts
            </th>
            <th className="py-2 pr-3 font-medium text-right">
              <Share2 size={12} className="inline mr-0.5" />Shares
            </th>
            <th className="py-2 pr-3 font-medium text-right">
              <Bookmark size={12} className="inline mr-0.5" />Saves
            </th>
            <th className="py-2 font-medium text-right">Eng.%</th>
            <th className="py-2 w-6"></th>
          </tr>
        </thead>
        <tbody>
          {posts.map((p) => {
            const eng =
              p.views
                ? Math.round(
                    (((p.likes ?? 0) + (p.comments ?? 0) + (p.shares ?? 0) + (p.saves ?? 0)) /
                      p.views) *
                      100 *
                      100,
                  ) / 100
                : null;
            return (
              <tr key={p.id} className="border-b border-[#f1f5f9] hover:bg-[#fdf9ee]">
                <td className="py-2 pr-3 text-[#64748b] text-xs whitespace-nowrap">
                  {p.publish_time ? fmtDate(p.publish_time) : "—"}
                </td>
                <td className="py-2 pr-3">
                  <span className="inline-block text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#f1f5f9] text-[#64748b]">
                    {formatLabel(p.post_type)}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right font-semibold text-[#0f172a]">
                  {val(p.views)}
                </td>
                <td className="py-2 pr-3 text-right text-[#475569]">{val(p.likes)}</td>
                <td className="py-2 pr-3 text-right text-[#475569]">{val(p.comments)}</td>
                <td className="py-2 pr-3 text-right text-[#475569]">{val(p.shares)}</td>
                <td className="py-2 pr-3 text-right text-[#475569]">{val(p.saves)}</td>
                <td className="py-2 text-right text-[#475569]">
                  {eng != null ? `${eng}%` : "—"}
                </td>
                <td className="py-2 pl-2">
                  {p.permalink && (
                    <a
                      href={p.permalink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[#94a3b8] hover:text-[#C9A227]"
                    >
                      <ExternalLink size={13} />
                    </a>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── Platform tab bar ─────────────────────────────────────────────────── */

function PlatformTabs({
  active,
  availableSet,
  onChange,
}: {
  active: string;
  availableSet: Set<string>;
  onChange: (p: string) => void;
}) {
  return (
    <div className="flex gap-2 flex-wrap">
      {PLATFORMS.map((p) => {
        const live = availableSet.has(p);
        const isActive = active === p;
        return (
          <button
            key={p}
            disabled={!live}
            onClick={() => live && onChange(p)}
            className={[
              "px-4 py-1.5 rounded-full text-sm font-medium transition-colors",
              isActive
                ? "bg-[#C9A227] text-white"
                : live
                ? "bg-[#f1f5f9] text-[#475569] hover:bg-[#e2e8f0]"
                : "bg-[#f8fafc] text-[#cbd5e1] cursor-not-allowed",
            ].join(" ")}
          >
            {PLATFORM_LABELS[p]}
            {!live && (
              <span className="ml-1.5 text-[9px] font-semibold uppercase tracking-wide opacity-60">
                soon
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ── Aggregate banner ─────────────────────────────────────────────────── */

function AggregateBanner({ summary, periodLabel }: { summary: NetworkScreenSummary; periodLabel: string }) {
  const agg = summary.aggregate;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {[
        { label: "Total Followers", value: val(agg.total_followers), icon: <Users size={14} /> },
        { label: `Views · ${periodLabel}`, value: val(agg.total_views_monthly), icon: <Eye size={14} /> },
        { label: `Posts · ${periodLabel}`, value: String(agg.total_posts_monthly), icon: <FileText size={14} /> },
        {
          label: "Platforms Live",
          value: `${agg.platforms_live} / ${agg.platforms_total}`,
          icon: <TrendingUp size={14} />,
        },
      ].map(({ label, value, icon }) => (
        <div
          key={label}
          className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex flex-col gap-1"
        >
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

/* ── Per-platform detail panel ────────────────────────────────────────── */

function PlatformDetail({
  platform,
  ratios,
  current,
  prior,
  mode,
  weekly,
}: {
  platform: string;
  ratios: NetworkScreenRatios | null;
  current: NetworkScreenMonthStats | null;
  prior: NetworkScreenMonthStats | null;
  mode: "month" | "mtd" | "rolling30" | "prevmonth";
  weekly?: NetworkScreenWeeklyComparison;
}) {
  if (!current) {
    return (
      <div className="py-20 text-center text-sm text-[#94a3b8]">
        {PLATFORM_LABELS[platform]} data is not yet connected.
      </div>
    );
  }

  // Labels must reflect the UTC calendar date — the backend windows are UTC,
  // and a local-time evening on the 31st is already the next month in UTC.
  const utc = new Date();
  const now = new Date(utc.getUTCFullYear(), utc.getUTCMonth(), utc.getUTCDate());
  const priorDate = new Date(now.getFullYear(), now.getMonth() - 1);
  const prior2Date = new Date(now.getFullYear(), now.getMonth() - 2);
  const curLabel = mode === "rolling30"
    ? "Last 30 days"
    : mode === "mtd"
    ? `${now.toLocaleString("default", { month: "long" })} 1-${now.getDate()}`
    : mode === "prevmonth"
    ? priorDate.toLocaleString("default", { month: "long", year: "numeric" })
    : `${now.toLocaleString("default", { month: "long", year: "numeric" })} · thru ${now.toLocaleString("default", { month: "short", day: "numeric" })}`;
  const priorLabel = mode === "rolling30"
    ? "30 days before"
    : mode === "mtd"
    ? `${priorDate.toLocaleString("default", { month: "long" })} 1-${now.getDate()}`
    : mode === "prevmonth"
    ? prior2Date.toLocaleString("default", { month: "long", year: "numeric" })
    : priorDate.toLocaleString("default", { month: "long", year: "numeric" });
  const periodLabel = mode === "rolling30" ? "Last 30 Days" : mode === "mtd" ? "Month to Date" : mode === "prevmonth" ? "Previous Month" : "Current Month";

  return (
    <div className="flex flex-col gap-6">
      {/* Collab warning */}
      {current.collab_data_warning && (
        <div className="flex items-start gap-2 rounded-xl bg-[#fffbeb] border border-[#fde68a] px-4 py-3 text-xs text-[#92400e]">
          <TriangleAlert size={14} className="mt-0.5 shrink-0 text-[#d97706]" />
          Collab post counts come from the nightly Instagram collab pull. Shares, saves, and reach are
          not available for posts owned by an athlete, so engagement rate on those posts runs low.
        </div>
      )}

      {/* Four key ratios */}
      {ratios && (
        <div>
          <h3 className="text-xs font-semibold text-[#64748b] uppercase tracking-wide mb-3">
            Key Ratios
          </h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <RatioCard
              label="Last 7 Days Views / Followers"
              value={ratios.weekly_views_to_followers != null ? `${ratios.weekly_views_to_followers}×` : "—"}
              description="Published-post views over the latest 7 days"
            />
            <RatioCard
              label="Views per Post / Followers"
              value={ratios.views_per_post_to_followers != null ? `${ratios.views_per_post_to_followers}×` : "—"}
              description="Avg post reach vs. follower count"
            />
            <RatioCard
              label="Avg Views per Reel/Video"
              value={ratios.avg_views_per_reel != null ? fmt(Math.round(ratios.avg_views_per_reel)) : "—"}
              description={periodLabel}
            />
            <RatioCard
              label="Reel/Video Engagement Rate"
              value={ratios.engagement_rate_reels != null ? `${ratios.engagement_rate_reels}%` : "—"}
              description="(Likes+Comments+Shares+Saves) ÷ Views"
            />
          </div>
        </div>
      )}

      {weekly && <WeeklyPulse weekly={weekly} />}

      {/* Month comparison */}
      <Section title={`${periodLabel} Comparison`}>
        <div className="overflow-x-auto">
          <div className="min-w-[31rem]">
            <div className="grid grid-cols-[minmax(12rem,1fr)_7rem_7rem_5rem] gap-2 text-xs text-[#94a3b8] mb-1">
              <span />
              <span className="text-right font-medium text-[#475569]">{curLabel}</span>
              <span className="text-right">{priorLabel}</span>
              <span className="text-right">Change</span>
            </div>
            <CompareRow label="Followers" current={current.followers} prior={prior?.followers ?? null} />
            <CompareRow label={`New Followers (${periodLabel.toLowerCase()})`} current={current.new_followers_monthly} prior={prior?.new_followers_monthly ?? null} />
            <CompareRow label={`Posts Published (${periodLabel.toLowerCase()})`} current={current.posts_monthly} prior={prior?.posts_monthly ?? null} />
            <CompareRow label="Avg Posts / Week (4-wk)" current={current.avg_posts_per_week} prior={prior?.avg_posts_per_week ?? null} />
            <CompareRow label={`Total Views (${periodLabel.toLowerCase()})`} current={current.total_views_monthly} prior={prior?.total_views_monthly ?? null} />
            <CompareRow label="Avg Views / Post" current={current.avg_views_per_post} prior={prior?.avg_views_per_post ?? null} />
            <CompareRow label="Engagement Rate %" current={current.engagement_rate_overall} prior={prior?.engagement_rate_overall ?? null} isPercent />
            <CompareRow label={`Collabs Published (${periodLabel.toLowerCase()})`} current={current.collabs_published_monthly} prior={prior?.collabs_published_monthly ?? null} />
          </div>
        </div>
      </Section>

      {/* Format breakdown */}
      <Section title={`${periodLabel} by Format`}>
        <FormatTable breakdown={current.format_breakdown} />
      </Section>
    </div>
  );
}

/* ── Root component ───────────────────────────────────────────────────── */

export default function NetworkScreenView({
  summaries,
  topPosts,
}: {
  summaries: {
    month: NetworkScreenSummary | null;
    mtd: NetworkScreenSummary | null;
    rolling30: NetworkScreenSummary | null;
    prevmonth: NetworkScreenSummary | null;
  };
  topPosts: NetworkScreenTopPost[];
}) {
  const [activePlatform, setActivePlatform] = useState("instagram");
  // Current month is the preferred default; its column header carries a
  // "thru <date>" marker so early-month low numbers read as in-progress.
  const [comparisonMode, setComparisonMode] = useState<"month" | "mtd" | "rolling30" | "prevmonth">("month");
  const [formatFilter, setFormatFilter] = useState("all");
  const [postRange, setPostRange] = useState("all");
  const [nowMs] = useState(() => Date.now());

  const summary = summaries[comparisonMode];
  const periodLabel = comparisonMode === "rolling30" ? "Last 30 Days" : comparisonMode === "mtd" ? "Month to Date" : comparisonMode === "prevmonth" ? "Previous Month" : "Current Month";

  if (!summary) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-10">
        <p className="text-sm text-[#94a3b8]">
          Could not load Channel Insights — check that the API is reachable.
        </p>
      </main>
    );
  }

  const availableSet = new Set(
    summary.platforms.filter((p) => p.available).map((p) => p.platform),
  );

  const activePlatformData = summary.platforms.find((p) => p.platform === activePlatform);

  return (
    <main className="max-w-6xl mx-auto px-4 py-8 flex flex-col gap-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[#0f172a]">Channel Insights</h1>
        <p className="text-sm text-[#64748b] mt-1">
          NIL TV&apos;s own social channels · Instagram live ·{" "}
          <span className="text-[#94a3b8]">
            Facebook, YouTube, TikTok, Snapchat, LinkedIn coming soon
          </span>
        </p>
      </div>

      {/* Aggregate totals across all live platforms */}
      <AggregateBanner summary={summary} periodLabel={periodLabel} />

      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-4 flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-[#0f172a]">Comparison Window</h2>
            <p className="text-xs text-[#64748b] mt-1">Switches every Channel Insights metric between equivalent periods.</p>
          </div>
          <div className="flex flex-wrap gap-1 rounded-lg bg-[#f1f5f9] p-1" role="group" aria-label="Comparison window">
            {([
              ["month", "Current month"],
              ["mtd", "Month to date"],
              ["prevmonth", "Previous month"],
              ["rolling30", "Last 30 days"],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setComparisonMode(value)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium ${comparisonMode === value ? "bg-white text-[#0f172a] shadow-sm" : "text-[#64748b]"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-[#64748b]">
          {comparisonMode === "prevmonth" && "The last complete calendar month vs. the month before it."}
          {comparisonMode === "month" && "The current calendar month so far vs. the previous complete calendar month. Early in a month the current column runs low by nature."}
          {comparisonMode === "mtd" && "Current month-to-date vs. the same number of days in the previous month."}
          {comparisonMode === "rolling30" && "The latest 30 days vs. the 30 days immediately before them."}
        </p>
      </div>

      {/* Platform selector + per-platform detail */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 flex flex-col gap-5">
        <PlatformTabs
          active={activePlatform}
          availableSet={availableSet}
          onChange={setActivePlatform}
        />
        <PlatformDetail
          platform={activePlatform}
          ratios={activePlatformData?.ratios ?? null}
          current={activePlatformData?.current_month ?? null}
          prior={activePlatformData?.prior_month ?? null}
          mode={comparisonMode}
          weekly={summary.weekly_comparison}
        />
      </div>

      {/* Best performing posts — all-time, not per-platform */}
      <Section title="Best Performing Posts · Instagram (All Time, by Views)">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <div className="flex items-center gap-1.5 text-xs text-[#94a3b8]">
            <Info size={12} />
            Engagement Rate = (Likes + Comments + Shares + Saves) ÷ Views × 100
          </div>
          <div className="flex gap-2">
            <select value={formatFilter} onChange={(event) => setFormatFilter(event.target.value)} className="border border-[#e2e8f0] rounded-md px-2 py-1.5 text-xs text-[#475569]">
              <option value="all">All formats</option>
              <option value="REELS">Reels</option>
              <option value="IMAGE">Images</option>
              <option value="CAROUSEL_ALBUM">Carousels</option>
              <option value="VIDEO">Video</option>
            </select>
            <select value={postRange} onChange={(event) => setPostRange(event.target.value)} className="border border-[#e2e8f0] rounded-md px-2 py-1.5 text-xs text-[#475569]">
              <option value="all">All dates</option>
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
            </select>
          </div>
        </div>
        <TopPostsTable posts={topPosts.filter((post) => {
          if (formatFilter !== "all" && post.post_type !== formatFilter) return false;
          if (postRange === "all" || !post.publish_time) return true;
          const cutoff = nowMs - Number(postRange) * 24 * 60 * 60 * 1000;
          return new Date(post.publish_time).getTime() >= cutoff;
        })} />
      </Section>
    </main>
  );
}

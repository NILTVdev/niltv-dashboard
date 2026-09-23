"use client";
import { useBrand } from "@/components/BrandProvider";
import { formatLabel } from "@/lib/formatLabels";

import { useState, useRef, useCallback, useMemo } from "react";
import {
  Upload, RefreshCw, CheckCircle2, XCircle, Loader2,
  FileText, Copy, Check, Calendar, Eye, Heart, MessageCircle,
  Share2, Bookmark, Search, ExternalLink, TrendingUp, Globe,
  Download,
} from "lucide-react";
import {
  ResponsiveContainer, XAxis, YAxis,
  CartesianGrid, Tooltip, AreaChart, Area,
  LineChart, Line, Legend,
} from "recharts";

function StatusBadge({ result }: { result: { ok: boolean; message: string } | null }) {
  if (!result) return null;
  return (
    <span className={`flex items-center gap-1 text-xs ${result.ok ? "text-emerald-600" : "text-red-500"}`}>
      {result.ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
      {result.message}
    </span>
  );
}

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

/* ── Types for weekly/performance report ─────────────── */

interface SummaryReportData {
  report: string;
  date: string;
  social: {
    start_label: string;
    alltime_posts: number;
    alltime_views: number;
    alltime_reach: number;
    cur_month_name: string;
    prev_month_name: string;
    cur_month: { posts: number; views: number; reach: number };
    prev_month: { posts: number; views: number; reach: number };
    cur_week_views: number;
    prev_week_views: number;
  };
  gsc: {
    cur_month_name: string;
    prev_month_name: string;
    cur_month: { clicks: number; impressions: number; avg_ctr: number; avg_position: number };
    prev_month: { clicks: number; impressions: number; avg_ctr: number; avg_position: number };
    cur_week: { clicks: number; impressions: number };
    prev_week: { clicks: number; impressions: number };
  };
}

/* ── Types for monthly report ────────────────────────── */

interface MonthlyPost {
  id: number;
  account_username: string;
  account_name: string;
  description: string;
  post_type: string;
  permalink: string | null;
  publish_time: string | null;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  reach: number;
  engagement: number;
}

interface MonthlyGSCEntry {
  page?: string;
  clicks: number;
  impressions: number;
  avg_ctr: number;
  avg_position: number;
}

interface DailyGSCPoint { date: string; clicks: number; impressions: number }
interface DailySocialPoint { date: string; views: number; engagement: number }
interface CumulativePoint { date: string; value: number }

interface MonthlyStats {
  social: {
    total_posts: number;
    total_views: number;
    total_likes: number;
    total_comments: number;
    total_shares: number;
    total_saves: number;
    total_reach: number;
    unique_accounts: number;
  };
  gsc: {
    total_clicks: number;
    total_impressions: number;
    avg_ctr: number;
    avg_position: number;
  };
}

interface AlltimeStats {
  social: {
    total_posts: number;
    total_views: number;
    total_likes: number;
    total_comments: number;
    total_shares: number;
    total_saves: number;
    total_reach: number;
    unique_accounts: number;
  };
  gsc: {
    total_impressions: number;
  };
}

interface AlltimeGSCPoint { date: string; impressions: number }
interface AlltimeNetworkPoint { date: string; views: number; reach: number }

interface MonthlyReportData {
  year: number;
  month: number;
  month_name: string;
  stats: MonthlyStats;
  alltime: AlltimeStats;
  alltime_gsc_daily: AlltimeGSCPoint[];
  alltime_network: AlltimeNetworkPoint[];
  prev_stats: MonthlyStats;
  prev_month_name: string;
  top_posts: {
    top_by_views: MonthlyPost[];
    top_by_engagement: MonthlyPost[];
  };
  gsc: {
    top_pages: MonthlyGSCEntry[];
  };
  gsc_daily: DailyGSCPoint[];
  social_daily: DailySocialPoint[];
}

/* ── Percent-change helper ───────────────────────────── */

function pctChange(current: number, previous: number): { label: string; positive: boolean } {
  if (previous === 0) return { label: current > 0 ? "+∞%" : "0%", positive: current > 0 };
  const change = ((current - previous) / previous) * 100;
  return { label: `${change >= 0 ? "+" : ""}${change.toFixed(1)}%`, positive: change >= 0 };
}

function ChangeBadge({ current, previous }: { current: number; previous: number }) {
  const { label, positive } = pctChange(current, previous);
  return (
    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${positive ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-500"}`}>
      {label}
    </span>
  );
}

/* ── Weekly/Performance Report Visual Card ───────────── */

function WeeklyReportCard({ data }: { data: SummaryReportData }) {
  const s = data.social;
  const g = data.gsc;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-[var(--brand)] text-white rounded-2xl p-6">
        <h2 className="text-lg font-bold">Performance Report</h2>
        <p className="text-sm text-white/70 mt-1">TrueBlue TV — as of {data.date}</p>
      </div>

      {/* All-Time Stats */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <TrendingUp size={14} className="text-[var(--brand)]" /> All-Time Social Media
          <span className="text-xs font-normal text-[#94a3b8] ml-1">({s.start_label} – {data.date})</span>
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <KPI icon={<FileText size={14} />} label="Total Posts" value={fmt(s.alltime_posts)} />
          <KPI icon={<Eye size={14} />} label="Total Views" value={fmt(s.alltime_views)} />
          <KPI icon={<Globe size={14} />} label="Projected Reach" value={`~${fmt(s.alltime_reach)}`} />
        </div>
      </div>

      {/* Month-over-Month Social */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <Calendar size={14} className="text-[var(--brand)]" /> Monthly Social Comparison
        </h3>
        <div className="grid grid-cols-2 gap-4">
          {/* Current Month */}
          <div className="bg-[#f8fafc] rounded-xl p-4 border border-[#f1f5f9]">
            <p className="text-xs font-medium text-[var(--brand)] mb-3">{s.cur_month_name} (MTD)</p>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Views</span>
                <span className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
                  {fmt(s.cur_month.views)} <ChangeBadge current={s.cur_month.views} previous={s.prev_month.views} />
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Reach</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(s.cur_month.reach)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Posts</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(s.cur_month.posts)}</span>
              </div>
            </div>
          </div>
          {/* Previous Month */}
          <div className="bg-[#f8fafc] rounded-xl p-4 border border-[#f1f5f9]">
            <p className="text-xs font-medium text-[#64748b] mb-3">{s.prev_month_name} (Full Month)</p>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Views</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(s.prev_month.views)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Reach</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(s.prev_month.reach)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Posts</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(s.prev_month.posts)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Week-over-Week Social */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <TrendingUp size={14} className="text-[#2563eb]" /> Week-over-Week Views
        </h3>
        <div className="flex items-center gap-6">
          <div>
            <p className="text-xs text-[#64748b]">This Week</p>
            <p className="text-2xl font-bold text-[#0f172a]">{fmt(s.cur_week_views)}</p>
          </div>
          <div className="text-2xl text-[#94a3b8]">→</div>
          <div>
            <p className="text-xs text-[#64748b]">Last Week</p>
            <p className="text-2xl font-bold text-[#94a3b8]">{fmt(s.prev_week_views)}</p>
          </div>
          <ChangeBadge current={s.cur_week_views} previous={s.prev_week_views} />
        </div>
      </div>

      {/* GSC Header */}
      <div className="bg-[var(--brand)] text-white rounded-2xl p-6">
        <h3 className="text-lg font-bold flex items-center gap-2">
          <Search size={16} /> Web Search Performance
        </h3>
        <div className="grid grid-cols-3 gap-4 mt-4">
          <div>
            <p className="text-xs text-white/60">{g.cur_month_name} Website Impressions</p>
            <p className="text-xl font-bold">{fmt(g.cur_month.impressions)}</p>
          </div>
          <div>
            <p className="text-xs text-white/60">Avg CTR</p>
            <p className="text-xl font-bold">{(g.cur_month.avg_ctr * 100).toFixed(1)}%</p>
          </div>
          <div>
            <p className="text-xs text-white/60">Avg Position</p>
            <p className="text-xl font-bold">{g.cur_month.avg_position.toFixed(1)}</p>
          </div>
        </div>
      </div>

      {/* GSC Comparisons */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <Search size={14} className="text-[var(--brand)]" /> Website Impressions Comparison
        </h3>
        <div className="grid grid-cols-2 gap-4">
          {/* MoM */}
          <div className="bg-[#f8fafc] rounded-xl p-4 border border-[#f1f5f9]">
            <p className="text-xs font-medium text-[var(--brand)] mb-3">Month-over-Month</p>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[#64748b]">Impressions</span>
              <span className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
                {fmt(g.cur_month.impressions)} <ChangeBadge current={g.cur_month.impressions} previous={g.prev_month.impressions} />
              </span>
            </div>
          </div>
          {/* WoW */}
          <div className="bg-[#f8fafc] rounded-xl p-4 border border-[#f1f5f9]">
            <p className="text-xs font-medium text-[#2563eb] mb-3">Week-over-Week</p>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[#64748b]">Impressions</span>
              <span className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
                {fmt(g.cur_week.impressions)} <ChangeBadge current={g.cur_week.impressions} previous={g.prev_week.impressions} />
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Monthly Report Visual Card ──────────────────────── */

function MonthlyReportCard({ data }: { data: MonthlyReportData }) {
  const { brand: uiBrand } = useBrand();
  const { stats, alltime, prev_stats, top_posts, gsc } = data;
  const s = stats.social;
  const g = stats.gsc;
  const ps = prev_stats.social;
  const pg = prev_stats.gsc;
  const at = alltime.social;

  const fmtAxis = (d: string) => {
    const dt = new Date(d + "T00:00:00Z");
    return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  };

  const fmtAxisMonthYear = (d: string) => {
    const dt = new Date(d + "T00:00:00Z");
    return dt.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
  };

  const fmtK = (v: number) => {
    if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`;
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)}k`;
    return String(v);
  };

  // Cumulative all-time impressions
  const cumulativeImpressions: CumulativePoint[] = useMemo(() => {
    let running = 0;
    const points: CumulativePoint[] = [];
    for (const d of data.alltime_gsc_daily) {
      running += d.impressions;
      points.push({ date: d.date, value: running });
    }
    return points;
  }, [data.alltime_gsc_daily]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-[var(--brand)] text-white rounded-2xl p-6">
        <h2 className="text-lg font-bold">{data.month_name} {data.year} — Monthly Report</h2>
        <p className="text-sm text-white/70 mt-1">TrueBlue TV Network Performance</p>
      </div>

      {/* All-Time KPI Grid */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <TrendingUp size={14} className="text-[var(--brand)]" /> All-Time Totals
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KPI icon={<Eye size={14} />} label="Views" value={fmt(at.total_views)} />
          <KPI icon={<Heart size={14} />} label="Likes" value={fmt(at.total_likes)} />
          <KPI icon={<MessageCircle size={14} />} label="Comments" value={fmt(at.total_comments)} />
          <KPI icon={<Share2 size={14} />} label="Shares" value={fmt(at.total_shares)} />
          <KPI icon={<Bookmark size={14} />} label="Saves" value={fmt(at.total_saves)} />
          <KPI icon={<Globe size={14} />} label="Reach" value={fmt(at.total_reach)} />
          <KPI icon={<FileText size={14} />} label="Posts" value={fmt(at.total_posts)} />
          <KPI icon={<Search size={14} />} label="Website Impressions" value={fmt(alltime.gsc.total_impressions)} />
        </div>
      </div>

      {/* All-Time Charts Side by Side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* All-Time Network Views & Reach */}
        {data.alltime_network.length > 1 && (
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
            <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
              <Eye size={14} className="text-[var(--brand)]" /> All-Time Views & Reach
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={data.alltime_network} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tickFormatter={fmtAxisMonthYear} tick={{ fontSize: 9, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tickFormatter={fmtK} tick={{ fontSize: 9, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={44} />
                <Tooltip
                  formatter={(value: unknown, name?: unknown) => [fmt(value as number), (name as string) || ""]}
                  labelFormatter={(label: unknown) => fmtAxisMonthYear(String(label))}
                  contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="views" name="Views" stroke={uiBrand.colors.brand} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="reach" name="Reach" stroke="#7c3aed" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Cumulative All-Time Website Impressions */}
        {cumulativeImpressions.length > 0 && (
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
            <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
              <Search size={14} className="text-[var(--brand)]" /> Cumulative Website Impressions
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={cumulativeImpressions} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="cumImpGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={uiBrand.colors.brand} stopOpacity={0.2} />
                    <stop offset="95%" stopColor={uiBrand.colors.brand} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tickFormatter={fmtAxisMonthYear} tick={{ fontSize: 9, fill: "#94a3b8" }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 9, fill: "#94a3b8" }} tickFormatter={fmtK} width={44} />
                <Tooltip
                  formatter={(value: unknown) => [fmt(value as number), "Impressions"]}
                  labelFormatter={(label: unknown) => fmtAxisMonthYear(String(label))}
                  contentStyle={{ fontSize: 11, borderRadius: 8 }}
                />
                <Area type="monotone" dataKey="value" name="Impressions" stroke={uiBrand.colors.brand} strokeWidth={2} fill="url(#cumImpGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Monthly KPI Grid */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <Calendar size={14} className="text-[var(--brand)]" /> {data.month_name} Totals
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KPI icon={<Eye size={14} />} label="Views" value={fmt(s.total_views)} />
          <KPI icon={<Heart size={14} />} label="Likes" value={fmt(s.total_likes)} />
          <KPI icon={<MessageCircle size={14} />} label="Comments" value={fmt(s.total_comments)} />
          <KPI icon={<Share2 size={14} />} label="Shares" value={fmt(s.total_shares)} />
          <KPI icon={<Bookmark size={14} />} label="Saves" value={fmt(s.total_saves)} />
          <KPI icon={<Globe size={14} />} label="Reach" value={fmt(s.total_reach)} />
          <KPI icon={<FileText size={14} />} label="Posts" value={fmt(s.total_posts)} />
          <KPI icon={<TrendingUp size={14} />} label="Accounts Collaborated With" value={fmt(s.unique_accounts)} />
        </div>
      </div>

      {/* Month-over-Month Comparison */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <Calendar size={14} className="text-[var(--brand)]" /> Month-over-Month Comparison
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-[#f8fafc] rounded-xl p-4 border border-[#f1f5f9]">
            <p className="text-xs font-medium text-[var(--brand)] mb-3">{data.month_name}</p>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Views</span>
                <span className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
                  {fmt(s.total_views)} <ChangeBadge current={s.total_views} previous={ps.total_views} />
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Posts</span>
                <span className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
                  {fmt(s.total_posts)} <ChangeBadge current={s.total_posts} previous={ps.total_posts} />
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Reach</span>
                <span className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
                  {fmt(s.total_reach)} <ChangeBadge current={s.total_reach} previous={ps.total_reach} />
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Website Impressions</span>
                <span className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
                  {fmt(g.total_impressions)} <ChangeBadge current={g.total_impressions} previous={pg.total_impressions} />
                </span>
              </div>
            </div>
          </div>
          <div className="bg-[#f8fafc] rounded-xl p-4 border border-[#f1f5f9]">
            <p className="text-xs font-medium text-[#64748b] mb-3">{data.prev_month_name}</p>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Views</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(ps.total_views)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Posts</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(ps.total_posts)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Reach</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(ps.total_reach)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748b]">Website Impressions</span>
                <span className="text-sm font-bold text-[#0f172a]">{fmt(pg.total_impressions)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Top Posts by Views */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <Eye size={14} className="text-[var(--brand)]" /> Top 5 Posts by Views
        </h3>
        <div className="space-y-3">
          {top_posts.top_by_views.map((p, i) => (
            <PostCard key={p.id} post={p} rank={i + 1} metric="views" />
          ))}
        </div>
      </div>

      {/* Top Posts by Engagement */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <Heart size={14} className="text-[#2563eb]" /> Top 5 Posts by Engagement
        </h3>
        <div className="space-y-3">
          {top_posts.top_by_engagement.map((p, i) => (
            <PostCard key={p.id} post={p} rank={i + 1} metric="engagement" />
          ))}
        </div>
      </div>

      {/* GSC Section */}
      <div className="bg-[var(--brand)] text-white rounded-2xl p-6">
        <h3 className="text-lg font-bold flex items-center gap-2">
          <Search size={16} /> Web Search Performance
        </h3>
        <div className="grid grid-cols-3 gap-4 mt-4">
          <div>
            <p className="text-xs text-white/60">Website Impressions</p>
            <p className="text-xl font-bold">{fmt(g.total_impressions)}</p>
          </div>
          <div>
            <p className="text-xs text-white/60">Avg CTR</p>
            <p className="text-xl font-bold">{(g.avg_ctr * 100).toFixed(1)}%</p>
          </div>
          <div>
            <p className="text-xs text-white/60">Avg Position</p>
            <p className="text-xl font-bold">{g.avg_position.toFixed(1)}</p>
          </div>
        </div>
      </div>

      {/* All-Time Daily Website Impressions */}
      {data.alltime_gsc_daily.length > 0 && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
          <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
            <Search size={14} className="text-[var(--brand)]" /> All-Time Website Impressions
          </h3>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={data.alltime_gsc_daily} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <defs>
                <linearGradient id="alltimeImpGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={uiBrand.colors.brand} stopOpacity={0.2} />
                  <stop offset="95%" stopColor={uiBrand.colors.brand} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tickFormatter={fmtAxisMonthYear} tick={{ fontSize: 10, fill: "#94a3b8" }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} tickFormatter={fmtK} />
              <Tooltip
                formatter={(value: unknown) => [fmt(value as number), "Impressions"]}
                labelFormatter={(label: unknown) => fmtAxis(String(label))}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <Area type="monotone" dataKey="impressions" name="Impressions" stroke={uiBrand.colors.brand} strokeWidth={2} fill="url(#alltimeImpGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Top Pages */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
          <Globe size={14} className="text-[var(--brand)]" /> Top Pages by Impressions
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
                <th className="py-2 pr-4 font-medium w-8">#</th>
                <th className="py-2 pr-4 font-medium">Page</th>
                <th className="py-2 pr-4 font-medium text-right">Impressions</th>
                <th className="py-2 pr-4 font-medium text-right">Clicks</th>
                <th className="py-2 pr-4 font-medium text-right">CTR</th>
                <th className="py-2 font-medium text-right">Position</th>
              </tr>
            </thead>
            <tbody>
              {gsc.top_pages.map((p, i) => {
                const shortPage = p.page ? p.page.replace(/^https?:\/\/[^/]+/, "") || "/" : "—";
                return (
                  <tr key={p.page} className="border-b border-[#f1f5f9]">
                    <td className="py-2 pr-4 text-[#94a3b8] text-xs">{i + 1}</td>
                    <td className="py-2 pr-4 text-[#0f172a] font-medium">
                      {p.page ? (
                        <a href={p.page} target="_blank" rel="noopener noreferrer" className="text-[var(--brand)] hover:underline flex items-center gap-1">
                          {shortPage} <ExternalLink size={10} />
                        </a>
                      ) : shortPage}
                    </td>
                    <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(p.impressions)}</td>
                    <td className="py-2 pr-4 text-right text-[#64748b]">{fmt(p.clicks)}</td>
                    <td className="py-2 pr-4 text-right text-[#64748b]">{(p.avg_ctr * 100).toFixed(1)}%</td>
                    <td className="py-2 text-right text-[#64748b]">{p.avg_position}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function KPI({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-4 flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-xs font-medium text-[#64748b]">
        {icon} {label}
      </span>
      <span className="text-xl font-bold text-[#0f172a]">{value}</span>
    </div>
  );
}

function PostCard({ post, rank, metric }: { post: MonthlyPost; rank: number; metric: "views" | "engagement" }) {
  const fmtDate = (iso: string | null) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  };

  return (
    <div className="flex items-start gap-3 p-3 rounded-xl bg-[#f8fafc] border border-[#f1f5f9]">
      <span className="text-lg font-bold text-[var(--brand)] min-w-[24px]">{rank}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-[var(--brand)]">@{post.account_username}</span>
          <span className="text-xs text-[#94a3b8]">{fmtDate(post.publish_time)}</span>
          {post.post_type && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#e2e8f0] text-[#64748b]">{formatLabel(post.post_type)}</span>
          )}
          {post.permalink && (
            <a href={post.permalink} target="_blank" rel="noopener noreferrer" className="text-[#94a3b8] hover:text-[var(--brand)]">
              <ExternalLink size={11} />
            </a>
          )}
        </div>
        {post.description && (
          <p className="text-xs text-[#64748b] mt-1 line-clamp-1">{post.description}</p>
        )}
        <div className="flex items-center gap-4 mt-2 text-xs text-[#64748b]">
          <span className={`flex items-center gap-1 ${metric === "views" ? "text-[var(--brand)] font-semibold" : ""}`}>
            <Eye size={11} /> {fmt(post.views)}
          </span>
          <span className={`flex items-center gap-1 ${metric === "engagement" ? "text-[#2563eb] font-semibold" : ""}`}>
            <Heart size={11} /> {fmt(post.likes)}
          </span>
          <span className="flex items-center gap-1">
            <MessageCircle size={11} /> {fmt(post.comments)}
          </span>
          <span className="flex items-center gap-1">
            <Share2 size={11} /> {fmt(post.shares)}
          </span>
          {metric === "engagement" && (
            <span className="text-[#2563eb] font-semibold">
              Total: {fmt(post.engagement)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Main Admin View ─────────────────────────────────── */

export default function AdminView() {
  // TrueBlue CSV Upload
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ ok: boolean; message: string } | null>(null);

  // NILTV Network CSV Upload
  const niltvFileInputRef = useRef<HTMLInputElement>(null);
  const [niltvUploading, setNiltvUploading] = useState(false);
  const [niltvUploadResult, setNiltvUploadResult] = useState<{ ok: boolean; message: string } | null>(null);

  // Web Analytics Pull
  const [pullingAnalytics, setPullingAnalytics] = useState(false);
  const [analyticsResult, setAnalyticsResult] = useState<{ ok: boolean; message: string } | null>(null);

  // Summary Report
  const [generatingReport, setGeneratingReport] = useState(false);
  const [summaryData, setSummaryData] = useState<SummaryReportData | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Monthly Report
  const [generatingMonthly, setGeneratingMonthly] = useState(false);
  const [monthlyData, setMonthlyData] = useState<MonthlyReportData | null>(null);
  const [monthlyError, setMonthlyError] = useState<string | null>(null);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const monthlyRef = useRef<HTMLDivElement>(null);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadResult(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/trueblue/upload", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        setUploadResult({ ok: false, message: data.error ?? "Upload failed" });
      } else {
        setUploadResult({
          ok: true,
          message:
            `${data.inserted} new, ${data.updated} updated` +
            (data.network_inserted != null
              ? ` · channel: ${data.network_inserted} new, ${data.network_updated} updated`
              : ""),
        });
      }
    } catch {
      setUploadResult({ ok: false, message: "Network error" });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleNiltvUpload = async (file: File) => {
    setNiltvUploading(true);
    setNiltvUploadResult(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/brand/upload", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        setNiltvUploadResult({ ok: false, message: data.error ?? "Upload failed" });
      } else {
        setNiltvUploadResult({ ok: true, message: `${data.inserted} new, ${data.updated} updated` });
      }
    } catch {
      setNiltvUploadResult({ ok: false, message: "Network error" });
    } finally {
      setNiltvUploading(false);
      if (niltvFileInputRef.current) niltvFileInputRef.current.value = "";
    }
  };

  const handlePullAnalytics = async () => {
    setPullingAnalytics(true);
    setAnalyticsResult(null);
    try {
      const res = await fetch("/api/proxy/api/web-analytics/pull", { method: "POST" });
      if (res.ok) {
        setAnalyticsResult({ ok: true, message: "Pull started — data will update in ~10s" });
      } else {
        const data = await res.json().catch(() => ({}));
        setAnalyticsResult({ ok: false, message: data.detail ?? `Error ${res.status}` });
      }
    } catch {
      setAnalyticsResult({ ok: false, message: "Network error" });
    } finally {
      setPullingAnalytics(false);
    }
  };

  const handleGenerateReport = async () => {
    setGeneratingReport(true);
    setSummaryData(null);
    setReportError(null);
    setCopied(false);
    try {
      const res = await fetch("/api/proxy/api/reports/summary");
      const data = await res.json();
      if (res.ok) {
        setSummaryData(data);
      } else {
        setReportError(data.detail ?? `Error ${res.status}`);
      }
    } catch {
      setReportError("Network error");
    } finally {
      setGeneratingReport(false);
    }
  };

  const handleCopy = async () => {
    if (!summaryData?.report) return;
    await navigator.clipboard.writeText(summaryData.report);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleMonthlyReport = async () => {
    setGeneratingMonthly(true);
    setMonthlyData(null);
    setMonthlyError(null);
    try {
      const res = await fetch("/api/proxy/api/reports/monthly");
      const data = await res.json();
      if (res.ok) {
        setMonthlyData(data);
      } else {
        setMonthlyError(data.detail ?? `Error ${res.status}`);
      }
    } catch {
      setMonthlyError("Network error");
    } finally {
      setGeneratingMonthly(false);
    }
  };

  const handleDownloadPdf = useCallback(async () => {
    if (!monthlyRef.current || !monthlyData) return;
    setDownloadingPdf(true);
    try {
      const html2canvas = (await import("html2canvas-pro")).default;
      const { jsPDF } = await import("jspdf");
      const el = monthlyRef.current;
      const canvas = await html2canvas(el, { scale: 2, useCORS: true, backgroundColor: "#f8fafc" });
      const imgData = canvas.toDataURL("image/png");
      const pxW = canvas.width;
      const pxH = canvas.height;
      const pdfW = 210; // A4 width in mm
      const pdfH = (pxH * pdfW) / pxW;
      const pdf = new jsPDF({ orientation: pdfH > 297 ? "portrait" : "portrait", unit: "mm", format: [pdfW, pdfH] });
      pdf.addImage(imgData, "PNG", 0, 0, pdfW, pdfH);
      pdf.save(`TrueBlue_Monthly_${monthlyData.month_name}_${monthlyData.year}.pdf`);
    } catch (err) {
      console.error("PDF generation failed:", err);
    } finally {
      setDownloadingPdf(false);
    }
  }, [monthlyData]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-[#0f172a] mb-1">Admin</h1>
        <p className="text-sm text-[#64748b]">Manual data management actions.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
        {/* Network CSV Upload */}
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-3">
          <h2 className="text-sm font-semibold text-[#0f172a]">TrueBlue Grid CSV Upload</h2>
          <p className="text-xs text-[#64748b]">
            Upload the Meta Business Suite content export of @trueblue_tv. It updates the TrueBlue
            page and files the same posts under the TrueBlueTV channel in the shared network table
            (tagged truebluetv). This is the channel&apos;s only feed: no token is available for
            this account, so the nightly API pulls skip it.
          </p>
          <div className="flex items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f); }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[var(--brand)] hover:border-[var(--brand)] transition-colors disabled:opacity-50"
            >
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {uploading ? "Importing…" : "Upload CSV"}
            </button>
            <StatusBadge result={uploadResult} />
          </div>
        </div>

        {/* NILTV Network CSV Upload */}
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-3">
          <h2 className="text-sm font-semibold text-[#0f172a]">NILTV Network CSV Upload</h2>
          <p className="text-xs text-[#64748b]">
            Upload a Meta Business Suite CSV export to backfill shares, saves, and reach on NILTV
            collab posts. NILTV posts pull nightly from the Instagram Graph API. Zoomph covers Duke
            accounts only and never feeds this table.
          </p>
          <div className="flex items-center gap-3">
            <input
              ref={niltvFileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleNiltvUpload(f); }}
            />
            <button
              onClick={() => niltvFileInputRef.current?.click()}
              disabled={niltvUploading}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[#C9A227] hover:border-[#C9A227] transition-colors disabled:opacity-50"
            >
              {niltvUploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {niltvUploading ? "Importing…" : "Upload CSV"}
            </button>
            <StatusBadge result={niltvUploadResult} />
          </div>
        </div>

        {/* Web Analytics Pull */}
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-3">
          <h2 className="text-sm font-semibold text-[#0f172a]">Web Analytics Pull</h2>
          <p className="text-xs text-[#64748b]">
            Manually trigger a GA4 + Search Console data pull (last 30 days). Normally runs daily at 4 AM UTC.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={handlePullAnalytics}
              disabled={pullingAnalytics}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[var(--brand)] hover:border-[var(--brand)] transition-colors disabled:opacity-50"
            >
              <RefreshCw size={14} className={pullingAnalytics ? "animate-spin" : ""} />
              {pullingAnalytics ? "Pulling…" : "Pull Fresh Data"}
            </button>
            <StatusBadge result={analyticsResult} />
          </div>
        </div>

        {/* Summary Report */}
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-3">
          <h2 className="text-sm font-semibold text-[#0f172a]">Performance Report</h2>
          <p className="text-xs text-[#64748b]">
            Generate a summary report with social media and web search stats for copy-pasting.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={handleGenerateReport}
              disabled={generatingReport}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[var(--brand)] hover:border-[var(--brand)] transition-colors disabled:opacity-50"
            >
              {generatingReport ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
              {generatingReport ? "Generating…" : "Generate Report"}
            </button>
            {reportError && (
              <span className="flex items-center gap-1 text-xs text-red-500">
                <XCircle size={12} /> {reportError}
              </span>
            )}
          </div>
        </div>

        {/* Monthly Report */}
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-3">
          <h2 className="text-sm font-semibold text-[#0f172a]">Monthly Report</h2>
          <p className="text-xs text-[#64748b]">
            Visual monthly report with top posts, best pages, and search rankings.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={handleMonthlyReport}
              disabled={generatingMonthly}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[var(--brand)] hover:border-[var(--brand)] transition-colors disabled:opacity-50"
            >
              {generatingMonthly ? <Loader2 size={14} className="animate-spin" /> : <Calendar size={14} />}
              {generatingMonthly ? "Generating…" : "Monthly Report"}
            </button>
            {monthlyError && (
              <span className="flex items-center gap-1 text-xs text-red-500">
                <XCircle size={12} /> {monthlyError}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Summary Report Output */}
      {summaryData && (
        <div className="space-y-4">
          <div className="flex items-center justify-end">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[var(--brand)] hover:border-[var(--brand)] transition-colors"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Copied!" : "Copy as Text"}
            </button>
          </div>
          <WeeklyReportCard data={summaryData} />
        </div>
      )}

      {/* Monthly Report Output */}
      {monthlyData && (
        <div className="space-y-4">
          <div className="flex items-center justify-end">
            <button
              onClick={handleDownloadPdf}
              disabled={downloadingPdf}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[var(--brand)] hover:border-[var(--brand)] transition-colors disabled:opacity-50"
            >
              {downloadingPdf ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
              {downloadingPdf ? "Generating PDF…" : "Download PDF"}
            </button>
          </div>
          <div ref={monthlyRef}>
            <MonthlyReportCard data={monthlyData} />
          </div>
        </div>
      )}
    </div>
  );
}

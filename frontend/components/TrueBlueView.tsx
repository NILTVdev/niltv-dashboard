"use client";
import { useBrand } from "@/components/BrandProvider";

import { useState, useCallback, useMemo, Fragment } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  BarChart,
  Bar,
  Legend,
} from "recharts";
import type {
  TrueBlueSnapshot,
  TrueBluePost,
  TrueBlueSummary,
  TrueBlueNetworkSummary,
  TrueBlueTopAccount,
  TrueBlueNetworkPost,
  TrueBlueNetworkPostSnapshot,
  NetworkMetricsOverTime,
} from "@/lib/types";
import { formatLabel } from "@/lib/formatLabels";
import { fmt, fmtDate } from "@/lib/utils";
import { Heart, MessageCircle, ImageIcon, Eye, Share2, Globe, TrendingUp, ChevronDown, ChevronRight, ChevronLeft, Loader2, ExternalLink } from "lucide-react";

const API = "/api/proxy";

/* ── Date Range ─────────────────────────────────────── */

const RANGES = [
  { key: "7", label: "7 Days" },
  { key: "14", label: "14 Days" },
  { key: "30", label: "30 Days" },
  { key: "90", label: "90 Days" },
  { key: "month", label: "This Month" },
  { key: "2026", label: "2026" },
  { key: "all", label: "All Time" },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

function rangeCutoff(range: RangeKey): string | null {
  if (range === "all") return null;
  if (range === "month") {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  }
  if (range === "2026") return "2026-01-01";
  const d = new Date();
  d.setDate(d.getDate() - Number(range));
  return d.toISOString().slice(0, 10);
}

/* ── Props ──────────────────────────────────────────── */

interface Props {
  profile: TrueBlueSnapshot | null;
  posts: TrueBluePost[];
  summary: TrueBlueSummary;
  networkSummary: TrueBlueNetworkSummary | null;
  topAccounts: TrueBlueTopAccount[];
  networkPosts: TrueBlueNetworkPost[];
  metricsOverTime: NetworkMetricsOverTime[];
}

/* ── KPI Card ───────────────────────────────────────── */

function KPI({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-xs font-medium text-[#64748b]">
        {icon} {label}
      </span>
      <span className="text-2xl font-bold text-[#0f172a]">{value}</span>
    </div>
  );
}

/* ── Custom Tooltip ─────────────────────────────────── */

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-[#e2e8f0] rounded-lg shadow-sm px-3 py-2 text-xs">
      <p className="font-medium text-[#0f172a] mb-1">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="text-[#64748b]">
          <span style={{ color: entry.color }}>●</span> {entry.name}: <span className="font-medium text-[#0f172a]">{fmt(entry.value)}</span>
        </p>
      ))}
    </div>
  );
}

/* ── @trueblue_tv Post Views Chart ──────────────────── */

function PostViewsChart({ posts }: { posts: TrueBluePost[] }) {
  const { brand: uiBrand } = useBrand();
  // Aggregate by date so multiple posts on the same day stack up
  const byDate = new Map<string, number>();
  for (const p of posts) {
    if (!p.posted_at || (p.video_view_count ?? 0) <= 0) continue;
    const d = p.posted_at.slice(0, 10); // ISO date for sorting
    byDate.set(d, (byDate.get(d) ?? 0) + (p.video_view_count ?? 0));
  }
  const data = [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, views]) => ({ date: fmtDate(date), views }));

  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet — check back after more posts.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={48} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="views" name="Views" fill={uiBrand.colors.brand} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ── @trueblue_tv Post Engagement Chart ─────────────── */

function PostEngagementChart({ posts }: { posts: TrueBluePost[] }) {
  // Aggregate by date, clamp negatives to 0
  const byDate = new Map<string, { likes: number; comments: number }>();
  for (const p of posts) {
    if (!p.posted_at) continue;
    const likes = Math.max(0, p.like_count ?? 0);
    const comments = Math.max(0, p.comment_count ?? 0);
    if (likes === 0 && comments === 0) continue;
    const d = p.posted_at.slice(0, 10); // ISO date for sorting
    const existing = byDate.get(d) ?? { likes: 0, comments: 0 };
    existing.likes += likes;
    existing.comments += comments;
    byDate.set(d, existing);
  }
  const data = [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, v]) => ({ date: fmtDate(date), likes: v.likes, comments: v.comments }));

  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet — check back after more posts.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={48} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="likes" name="Likes" fill="#2563eb" stackId="engagement" />
        <Bar dataKey="comments" name="Comments" fill="#64748b" stackId="engagement" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ── Top Accounts Bar Chart ───────────────────────── */

const CHART_ACCOUNTS_PER_PAGE = 10;

function truncateUsername(name: string, max = 12): string {
  return name.length > max ? name.slice(0, max) + "…" : name;
}

function TopAccountsChart({ accounts }: { accounts: TrueBlueTopAccount[] }) {
  const { brand: uiBrand } = useBrand();
  const [page, setPage] = useState(0);
  const totalPages = Math.ceil(accounts.length / CHART_ACCOUNTS_PER_PAGE);
  const pageAccounts = accounts.slice(page * CHART_ACCOUNTS_PER_PAGE, (page + 1) * CHART_ACCOUNTS_PER_PAGE);

  const data = pageAccounts.map((a) => ({
    name: truncateUsername(a.account_username),
    fullName: a.account_username,
    views: a.total_views,
  }));

  if (!data.length) return null;

  return (
    <div>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 60, left: 0 }} layout="horizontal">
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} angle={-45} textAnchor="end" interval={0} />
          <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={56} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const entry = payload[0];
              return (
                <div className="bg-white border border-[#e2e8f0] rounded-lg shadow-sm px-3 py-2 text-xs">
                  <p className="font-medium text-[#0f172a] mb-1">@{(entry.payload as { fullName: string }).fullName}</p>
                  <p className="text-[#64748b]">Views: <span className="font-medium text-[#0f172a]">{fmt(entry.value as number)}</span></p>
                </div>
              );
            }}
          />
          <Bar dataKey="views" name="Views" fill={uiBrand.colors.brand} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs text-[#94a3b8]">{accounts.length} accounts</span>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="p-1 rounded text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-30 disabled:cursor-not-allowed">
              <ChevronLeft size={14} />
            </button>
            <span className="text-xs text-[#64748b]">{page + 1} / {totalPages}</span>
            <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="p-1 rounded text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-30 disabled:cursor-not-allowed">
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Top Accounts Table (paginated) ──────────────── */

const ACCOUNTS_PER_PAGE = 10;

function TopAccountsTable({ accounts }: { accounts: TrueBlueTopAccount[] }) {
  const [page, setPage] = useState(0);

  if (!accounts.length) return null;

  const totalPages = Math.ceil(accounts.length / ACCOUNTS_PER_PAGE);
  const pageAccounts = accounts.slice(page * ACCOUNTS_PER_PAGE, (page + 1) * ACCOUNTS_PER_PAGE);

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
              <th className="py-2 pr-4 font-medium">Account</th>
              <th className="py-2 pr-4 font-medium text-right">Posts</th>
              <th className="py-2 pr-4 font-medium text-right">Views</th>
              <th className="py-2 pr-4 font-medium text-right">Likes</th>
              <th className="py-2 font-medium text-right">Comments</th>
            </tr>
          </thead>
          <tbody>
            {pageAccounts.map((a) => (
              <tr key={a.account_username} className="border-b border-[#f1f5f9] hover:bg-[#f8fafc]">
                <td className="py-2 pr-4">
                  <a
                    href={`https://www.instagram.com/${a.account_username}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--brand)] hover:underline font-medium"
                  >
                    @{a.account_username}
                  </a>
                </td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(a.post_count)}</td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(a.total_views)}</td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(a.total_likes)}</td>
                <td className="py-2 text-right text-[#0f172a]">{fmt(a.total_comments)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-[#94a3b8]">{accounts.length} accounts</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1 rounded text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="text-xs text-[#64748b]">{page + 1} / {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="p-1 rounded text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Network Views Over Time (split chart) ─────────── */

function NetworkViewsChart({ data }: { data: NetworkMetricsOverTime[] }) {
  const { brand: uiBrand } = useBrand();
  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough snapshot data yet.
      </div>
    );
  }

  const hasProjected = data.some((d) => d.total_projected_reach > d.total_reach);
  const chartData = data.map((d) => ({
    date: fmtDate(d.date),
    views: d.total_views,
    reach: d.total_reach,
    ...(hasProjected ? { projectedReach: d.total_projected_reach } : {}),
  }));

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={56} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="views" name="Views" stroke={uiBrand.colors.brand} strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="reach" name="Reach" stroke="#7c3aed" strokeWidth={2} dot={false} />
        {hasProjected && (
          <Line type="monotone" dataKey="projectedReach" name="Proj. Reach" stroke="#7c3aed" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ── Network Engagement Over Time (split chart) ────── */

function NetworkEngagementChart({ data }: { data: NetworkMetricsOverTime[] }) {
  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough snapshot data yet.
      </div>
    );
  }

  const chartData = data.map((d) => ({
    date: fmtDate(d.date),
    likes: d.total_likes,
    comments: d.total_comments,
    shares: d.total_shares,
  }));

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={56} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="likes" name="Likes" stroke="#2563eb" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="comments" name="Comments" stroke="#64748b" strokeWidth={1.5} dot={false} />
        <Line type="monotone" dataKey="shares" name="Shares" stroke="#059669" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ── Account-Level Charts (from network posts by publish date) ────── */

function AccountViewsChart({ posts }: { posts: TrueBlueNetworkPost[] }) {
  const { brand: uiBrand } = useBrand();
  const data = [...posts]
    .filter((p) => p.publish_time != null)
    .sort((a, b) => (a.publish_time ?? "").localeCompare(b.publish_time ?? ""))
    .map((p) => ({
      date: fmtDate(p.publish_time),
      views: p.views ?? 0,
      reach: p.reach ?? 0,
      projectedReach: p.projected_reach ?? p.reach ?? 0,
    }));

  const hasProjected = data.some((d) => d.projectedReach > d.reach);

  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet — check back after more posts.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={56} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="views" name="Views" stroke={uiBrand.colors.brand} strokeWidth={2} dot={{ r: 2, fill: uiBrand.colors.brand }} activeDot={{ r: 4 }} />
        <Line type="monotone" dataKey="reach" name="Reach" stroke="#7c3aed" strokeWidth={2} dot={{ r: 2, fill: "#7c3aed" }} activeDot={{ r: 4 }} />
        {hasProjected && (
          <Line type="monotone" dataKey="projectedReach" name="Proj. Reach" stroke="#7c3aed" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

function AccountEngagementChart({ posts }: { posts: TrueBlueNetworkPost[] }) {
  const data = [...posts]
    .filter((p) => p.publish_time != null)
    .sort((a, b) => (a.publish_time ?? "").localeCompare(b.publish_time ?? ""))
    .map((p) => ({
      date: fmtDate(p.publish_time),
      likes: p.likes ?? 0,
      comments: p.comments ?? 0,
      shares: p.shares ?? 0,
    }));

  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet — check back after more posts.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={56} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="likes" name="Likes" stroke="#2563eb" strokeWidth={2} dot={{ r: 2, fill: "#2563eb" }} activeDot={{ r: 4 }} />
        <Line type="monotone" dataKey="comments" name="Comments" stroke="#64748b" strokeWidth={1.5} dot={{ r: 2 }} />
        <Line type="monotone" dataKey="shares" name="Shares" stroke="#059669" strokeWidth={1.5} dot={{ r: 2 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ── Cumulative Account Charts (running totals over time) ─────────── */

function buildCumulativeViews(posts: TrueBlueNetworkPost[]) {
  const sorted = [...posts]
    .filter((p) => p.publish_time != null)
    .sort((a, b) => (a.publish_time ?? "").localeCompare(b.publish_time ?? ""));
  return sorted.reduce<{ date: string; views: number; reach: number; projectedReach: number }[]>((acc, p) => {
    const prev = acc.length ? acc[acc.length - 1] : { views: 0, reach: 0, projectedReach: 0 };
    const reach = prev.reach + (p.reach ?? 0);
    acc.push({
      date: fmtDate(p.publish_time),
      views: prev.views + (p.views ?? 0),
      reach,
      projectedReach: reach + (prev.projectedReach - prev.reach) + (p.projected_reach ?? 0),
    });
    return acc;
  }, []);
}

function AccountCumulativeViewsChart({ posts }: { posts: TrueBlueNetworkPost[] }) {
  const { brand: uiBrand } = useBrand();
  const data = buildCumulativeViews(posts);

  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet.
      </div>
    );
  }

  const hasProjected = data.some((d) => d.projectedReach > d.reach);

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={56} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="views" name="Total Views" stroke={uiBrand.colors.brand} strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="reach" name="Total Reach" stroke="#7c3aed" strokeWidth={2} dot={false} />
        {hasProjected && (
          <Line type="monotone" dataKey="projectedReach" name="Total Proj. Reach" stroke="#7c3aed" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

function buildCumulativeEngagement(posts: TrueBlueNetworkPost[]) {
  const sorted = [...posts]
    .filter((p) => p.publish_time != null)
    .sort((a, b) => (a.publish_time ?? "").localeCompare(b.publish_time ?? ""));
  return sorted.reduce<{ date: string; likes: number; comments: number; shares: number }[]>((acc, p) => {
    const prev = acc.length ? acc[acc.length - 1] : { likes: 0, comments: 0, shares: 0 };
    acc.push({
      date: fmtDate(p.publish_time),
      likes: prev.likes + (p.likes ?? 0),
      comments: prev.comments + (p.comments ?? 0),
      shares: prev.shares + (p.shares ?? 0),
    });
    return acc;
  }, []);
}

function AccountCumulativeEngagementChart({ posts }: { posts: TrueBlueNetworkPost[] }) {
  const data = buildCumulativeEngagement(posts);

  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={56} />
        <Tooltip content={<ChartTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="likes" name="Total Likes" stroke="#2563eb" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="comments" name="Total Comments" stroke="#64748b" strokeWidth={1.5} dot={false} />
        <Line type="monotone" dataKey="shares" name="Total Shares" stroke="#059669" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ── Post History Charts (per-post, split views+reach / engagement) ── */

function PostHistoryCharts({ snapshots, post }: { snapshots: TrueBlueNetworkPostSnapshot[]; post: TrueBlueNetworkPost }) {
  const { brand: uiBrand } = useBrand();
  const data = [
    ...snapshots.map((s) => ({
      date: fmtDate(s.captured_at),
      views: s.views ?? 0,
      reach: s.reach ?? 0,
      projectedReach: s.projected_reach ?? s.reach ?? 0,
      likes: s.likes ?? 0,
      comments: s.comments ?? 0,
      shares: s.shares ?? 0,
    })),
    {
      date: "Current",
      views: post.views ?? 0,
      reach: post.reach ?? 0,
      projectedReach: post.projected_reach ?? post.reach ?? 0,  // projected_reach only set when reach is missing
      likes: post.likes ?? 0,
      comments: post.comments ?? 0,
      shares: post.shares ?? 0,
    },
  ];

  const hasProjected = data.some((d) => d.projectedReach > d.reach);

  if (data.length < 2) {
    return (
      <div className="h-32 flex items-center justify-center text-xs text-[#94a3b8]">
        Only one data point — more will appear after future CSV imports.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div>
        <h5 className="text-xs font-medium text-[#64748b] mb-2">Views &amp; Reach</h5>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
            <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 9, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={44} />
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="views" name="Views" stroke={uiBrand.colors.brand} strokeWidth={2} dot={{ r: 2 }} />
            <Line type="monotone" dataKey="reach" name="Reach" stroke="#7c3aed" strokeWidth={2} dot={{ r: 2 }} />
            {hasProjected && (
              <Line type="monotone" dataKey="projectedReach" name="Proj. Reach" stroke="#7c3aed" strokeWidth={1.5} strokeDasharray="6 3" dot={{ r: 2 }} />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div>
        <h5 className="text-xs font-medium text-[#64748b] mb-2">Engagement</h5>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
            <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 9, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={44} />
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="likes" name="Likes" stroke="#2563eb" strokeWidth={2} dot={{ r: 2 }} />
            <Line type="monotone" dataKey="comments" name="Comments" stroke="#64748b" strokeWidth={1.5} dot={{ r: 2 }} />
            <Line type="monotone" dataKey="shares" name="Shares" stroke="#059669" strokeWidth={1.5} dot={{ r: 2 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ── Network Posts Table with Expandable History ───── */

const POSTS_PER_PAGE = 25;

function NetworkPostsTable({ networkPosts }: { networkPosts: TrueBlueNetworkPost[] }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [historyCache, setHistoryCache] = useState<Record<number, TrueBlueNetworkPostSnapshot[]>>({});
  const [errorCache, setErrorCache] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState<number | null>(null);
  const [accountFilter, setAccountFilter] = useState<string>("");
  const [sortBy, setSortBy] = useState<"views" | "likes" | "publish_time">("views");
  const [page, setPage] = useState(0);

  const uniqueAccounts = [...new Set(networkPosts.map((p) => p.account_username).filter(Boolean))].sort() as string[];

  const filtered = networkPosts
    .filter((p) => !accountFilter || p.account_username === accountFilter)
    .sort((a, b) => {
      if (sortBy === "publish_time") return (b.publish_time ?? "").localeCompare(a.publish_time ?? "");
      return (b[sortBy] ?? 0) - (a[sortBy] ?? 0);
    });

  const totalPages = Math.ceil(filtered.length / POSTS_PER_PAGE);
  const pagePosts = filtered.slice(page * POSTS_PER_PAGE, (page + 1) * POSTS_PER_PAGE);

  const fetchHistory = useCallback(async (postId: number) => {
    if (historyCache[postId]) return;
    setLoading(postId);
    try {
      const res = await fetch(`${API}/api/trueblue/network/posts/${postId}/history`);
      if (res.ok) {
        const data: TrueBlueNetworkPostSnapshot[] = await res.json();
        setHistoryCache((prev) => ({ ...prev, [postId]: data }));
      } else {
        setErrorCache((prev) => ({ ...prev, [postId]: `API returned ${res.status}` }));
      }
    } catch (err) {
      setErrorCache((prev) => ({ ...prev, [postId]: `Fetch failed: ${err instanceof Error ? err.message : "network error"}` }));
    } finally {
      setLoading(null);
    }
  }, [historyCache]);

  const toggleExpand = (postId: number) => {
    if (expandedId === postId) {
      setExpandedId(null);
    } else {
      setExpandedId(postId);
      fetchHistory(postId);
    }
  };

  if (!networkPosts.length) {
    return <p className="text-sm text-[#94a3b8] py-4">No network posts available yet.</p>;
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={accountFilter}
          onChange={(e) => { setAccountFilter(e.target.value); setPage(0); }}
          className="text-xs border border-[#e2e8f0] rounded-lg px-3 py-1.5 bg-white text-[#0f172a]"
        >
          <option value="">All accounts ({networkPosts.length})</option>
          {uniqueAccounts.map((a) => (
            <option key={a} value={a}>@{a}</option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => { setSortBy(e.target.value as "views" | "likes" | "publish_time"); setPage(0); }}
          className="text-xs border border-[#e2e8f0] rounded-lg px-3 py-1.5 bg-white text-[#0f172a]"
        >
          <option value="views">Sort by Views</option>
          <option value="likes">Sort by Likes</option>
          <option value="publish_time">Sort by Date</option>
        </select>
        <span className="text-xs text-[#94a3b8] self-center">{filtered.length} posts</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
              <th className="py-2 pr-2 font-medium w-8"></th>
              <th className="py-2 pr-4 font-medium">Account</th>
              <th className="py-2 pr-4 font-medium">Published</th>
              <th className="py-2 pr-4 font-medium">Type</th>
              <th className="py-2 pr-4 font-medium text-right">Views</th>
              <th className="py-2 pr-4 font-medium text-right">Reach</th>
              <th className="py-2 pr-4 font-medium text-right">Likes</th>
              <th className="py-2 pr-4 font-medium text-right">Comments</th>
              <th className="py-2 pr-4 font-medium text-right">Shares</th>
              <th className="py-2 font-medium w-8"></th>
            </tr>
          </thead>
          <tbody>
            {pagePosts.map((p) => {
              const isExpanded = expandedId === p.id;
              const history = historyCache[p.id];
              const error = errorCache[p.id];
              const isLoading = loading === p.id;

              return (
                <Fragment key={p.id}>
                  <tr
                    className="border-b border-[#f1f5f9] hover:bg-[#f8fafc] cursor-pointer"
                    onClick={() => toggleExpand(p.id)}
                  >
                    <td className="py-2 pr-2 text-[#94a3b8]">
                      {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </td>
                    <td className="py-2 pr-4">
                      <span className="text-[var(--brand)] font-medium">@{p.account_username}</span>
                      {p.account_name && <span className="text-[#94a3b8] ml-1.5 text-xs">{p.account_name}</span>}
                    </td>
                    <td className="py-2 pr-4 text-[#64748b] text-xs">{fmtDate(p.publish_time)}</td>
                    <td className="py-2 pr-4 text-[#64748b] text-xs">{formatLabel(p.post_type)}</td>
                    <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(p.views)}</td>
                    <td className="py-2 pr-4 text-right text-[#0f172a]">
                      {p.reach ? (
                        fmt(p.reach)
                      ) : p.projected_reach ? (
                        <span className="text-[#94a3b8] italic" title="Projected from avg reach/views ratio">~{fmt(p.projected_reach)}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(p.likes)}</td>
                    <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(p.comments)}</td>
                    <td className="py-2 pr-4 text-right text-[#0f172a]">{fmt(p.shares)}</td>
                    <td className="py-2">
                      {p.permalink && (
                        <a
                          href={p.permalink}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[#94a3b8] hover:text-[var(--brand)]"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="border-b border-[#e2e8f0]">
                      <td colSpan={10} className="py-4 px-4 bg-[#f8fafc]">
                        <div className="space-y-3">
                          {p.description && (
                            <p className="text-xs text-[#64748b] line-clamp-2">{p.description}</p>
                          )}
                          <div className="flex flex-wrap gap-4 text-xs text-[#64748b]">
                            <span>Saves: {fmt(p.saves)}</span>
                            <span>Follows: {fmt(p.follows)}</span>
                            {p.duration_sec != null && <span>Duration: {p.duration_sec}s</span>}
                          </div>
                          <div>
                            <h4 className="text-xs font-semibold text-[#0f172a] mb-2 flex items-center gap-1.5">
                              <TrendingUp size={12} /> Metrics Over Time
                            </h4>
                            {isLoading ? (
                              <div className="h-32 flex items-center justify-center">
                                <Loader2 size={16} className="animate-spin text-[#94a3b8]" />
                              </div>
                            ) : error ? (
                              <div className="h-20 flex items-center justify-center text-xs text-red-400">
                                {error}
                              </div>
                            ) : history ? (
                              <PostHistoryCharts snapshots={history} post={p} />
                            ) : (
                              <div className="h-20 flex items-center justify-center text-xs text-[#94a3b8]">
                                No historical snapshots yet — data will appear after future CSV imports.
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-[#94a3b8]">{filtered.length} posts</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1 rounded text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="text-xs text-[#64748b]">{page + 1} / {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="p-1 rounded text-[#64748b] hover:bg-[#f1f5f9] disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Main View ──────────────────────────────────────── */

export default function TrueBlueView({ profile, posts, summary, networkSummary, topAccounts, networkPosts, metricsOverTime }: Props) {
  const [range, setRange] = useState<RangeKey>("all");
  const [networkAccount, setNetworkAccount] = useState<string>("");

  const cutoff = rangeCutoff(range);

  // Unique network accounts for the dropdown
  const uniqueNetworkAccounts = useMemo(
    () => [...new Set(networkPosts.map((p) => p.account_username).filter(Boolean))].sort() as string[],
    [networkPosts],
  );

  // Filter data by date range
  const filteredPosts = useMemo(
    () => (cutoff ? posts.filter((p) => (p.posted_at ?? "") >= cutoff) : posts),
    [posts, cutoff],
  );

  const filteredNetworkPosts = useMemo(
    () => networkPosts
      .filter((p) => !cutoff || (p.publish_time ?? "") >= cutoff)
      .filter((p) => !networkAccount || p.account_username === networkAccount),
    [networkPosts, cutoff, networkAccount],
  );

  const filteredMetrics = useMemo(
    () => (cutoff ? metricsOverTime.filter((m) => m.date >= cutoff) : metricsOverTime),
    [metricsOverTime, cutoff],
  );

  // Recompute network KPIs from filtered posts
  const filteredNetworkKPIs = useMemo(() => {
    if (!filteredNetworkPosts.length) return null;
    const accounts = new Set<string>();
    let views = 0, likes = 0, comments = 0, shares = 0, reach = 0, projectedReach = 0;
    for (const p of filteredNetworkPosts) {
      views += p.views ?? 0;
      likes += p.likes ?? 0;
      comments += p.comments ?? 0;
      shares += p.shares ?? 0;
      reach += p.reach ?? 0;
      projectedReach += p.projected_reach ?? 0;
      if (p.account_username) accounts.add(p.account_username);
    }
    return {
      total_posts: filteredNetworkPosts.length,
      total_views: views,
      total_likes: likes,
      total_comments: comments,
      total_shares: shares,
      total_reach: reach,
      total_projected_reach: reach + projectedReach,
      unique_accounts: accounts.size,
    };
  }, [filteredNetworkPosts]);

  // Compute top accounts from filtered network posts (all accounts, not just selected one)
  const filteredAllNetworkPosts = useMemo(
    () => (cutoff ? networkPosts.filter((p) => (p.publish_time ?? "") >= cutoff) : networkPosts),
    [networkPosts, cutoff],
  );

  const filteredTopAccounts = useMemo(() => {
    const map = new Map<string, { account_username: string; account_name: string; post_count: number; total_views: number; total_likes: number; total_comments: number }>();
    for (const p of filteredAllNetworkPosts) {
      const key = p.account_username ?? "";
      const existing = map.get(key);
      if (existing) {
        existing.post_count += 1;
        existing.total_views += p.views ?? 0;
        existing.total_likes += p.likes ?? 0;
        existing.total_comments += p.comments ?? 0;
      } else {
        map.set(key, {
          account_username: p.account_username ?? "",
          account_name: p.account_name ?? "",
          post_count: 1,
          total_views: p.views ?? 0,
          total_likes: p.likes ?? 0,
          total_comments: p.comments ?? 0,
        });
      }
    }
    return [...map.values()].sort((a, b) => b.total_views - a.total_views).slice(0, 20);
  }, [filteredAllNetworkPosts]);

  // Use server-side summary for unfiltered "all" view, client-computed otherwise
  const isFiltered = range !== "all" || networkAccount !== "";
  const displayKPIs = !isFiltered && networkSummary ? {
    total_posts: networkSummary.total_posts,
    total_views: networkSummary.total_views,
    total_likes: networkSummary.total_likes,
    total_comments: networkSummary.total_comments,
    total_shares: networkSummary.total_shares,
    total_reach: networkSummary.total_reach,
    total_projected_reach: networkSummary.total_projected_reach,
    unique_accounts: networkSummary.unique_accounts,
  } : filteredNetworkKPIs;

  const displayTopAccounts = !isFiltered ? topAccounts : filteredTopAccounts;

  return (
    <div className="space-y-6">
      {/* Header + Date Range */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a] mb-1">TrueBlue TV</h1>
          <p className="text-sm text-[#64748b]">
            Instagram analytics for{" "}
            <a
              href="https://www.instagram.com/trueblue_tv/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--brand)] hover:underline"
            >
              @trueblue_tv
            </a>
            {profile?.bio && (
              <span className="ml-2 text-[#94a3b8]">— {profile.bio}</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={networkAccount}
            onChange={(e) => setNetworkAccount(e.target.value)}
            className="text-xs border border-[#e2e8f0] rounded-lg px-3 py-1.5 bg-white text-[#0f172a]"
          >
            <option value="">All accounts ({uniqueNetworkAccounts.length})</option>
            {uniqueNetworkAccounts.map((a) => (
              <option key={a} value={a}>@{a}</option>
            ))}
          </select>
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
        </div>
      </div>

      {/* Network KPIs */}
      {displayKPIs && (
        <>
          <h2 className="text-sm font-semibold text-[#0f172a]">
            {networkAccount ? `@${networkAccount}` : "Network Overview (All Affiliated Accounts)"}
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <KPI icon={<Eye size={14} />} label="Total Views" value={fmt(displayKPIs.total_views)} />
            <KPI icon={<Heart size={14} />} label="Total Likes" value={fmt(displayKPIs.total_likes)} />
            <KPI icon={<MessageCircle size={14} />} label="Comments" value={fmt(displayKPIs.total_comments)} />
            <KPI icon={<Share2 size={14} />} label="Shares" value={fmt(displayKPIs.total_shares)} />
            <KPI icon={<ImageIcon size={14} />} label="Posts" value={fmt(displayKPIs.total_posts)} />
            <KPI icon={<Globe size={14} />} label="Accounts" value={fmt(displayKPIs.unique_accounts)} />
          </div>
        </>
      )}

      {/* Network / Account Charts */}
      {networkAccount ? (
        /* Account-level charts from filtered network posts */
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
            <h2 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
              <Eye size={14} /> @{networkAccount} Views &amp; Reach
            </h2>
            <AccountViewsChart posts={filteredNetworkPosts} />
          </div>
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
            <h2 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
              <Heart size={14} /> @{networkAccount} Engagement
            </h2>
            <AccountEngagementChart posts={filteredNetworkPosts} />
          </div>
        </div>
      ) : (
        /* Network-wide charts + @trueblue_tv charts */
        <>
          {filteredMetrics.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
                <h2 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
                  <Eye size={14} /> Network Views &amp; Reach
                </h2>
                <NetworkViewsChart data={filteredMetrics} />
              </div>
              <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
                <h2 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
                  <Heart size={14} /> Network Engagement
                </h2>
                <NetworkEngagementChart data={filteredMetrics} />
              </div>
            </div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
              <h2 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
                <Eye size={14} /> @trueblue_tv Views
              </h2>
              <PostViewsChart posts={filteredPosts} />
            </div>
            <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
              <h2 className="text-sm font-semibold text-[#0f172a] mb-4 flex items-center gap-1.5">
                <Heart size={14} /> @trueblue_tv Engagement
              </h2>
              <PostEngagementChart posts={filteredPosts} />
            </div>
          </div>
        </>
      )}

      {/* Top Accounts (hidden when filtering by account) */}
      {!networkAccount && displayTopAccounts.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
            <h2 className="text-sm font-semibold text-[#0f172a] mb-4">Top Accounts by Views</h2>
            <TopAccountsChart accounts={displayTopAccounts} />
          </div>
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
            <h2 className="text-sm font-semibold text-[#0f172a] mb-4">Network Accounts</h2>
            <TopAccountsTable accounts={displayTopAccounts} />
          </div>
        </div>
      )}

      {/* Network Posts with Per-Post History */}
      {filteredNetworkPosts.length > 0 && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
          <h2 className="text-sm font-semibold text-[#0f172a] mb-4">
            Network Posts ({filteredNetworkPosts.length})
          </h2>
          <p className="text-xs text-[#94a3b8] mb-4">Click a row to view its metric history over time.</p>
          <NetworkPostsTable networkPosts={filteredNetworkPosts} />
        </div>
      )}
    </div>
  );
}

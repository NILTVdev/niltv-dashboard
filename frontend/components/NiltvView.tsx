"use client";

import { useState, useMemo } from "react";
import type { BrandSnapshot, NiltvNetworkPost, NiltvNetworkSummary } from "@/lib/types";
import { formatLabel } from "@/lib/formatLabels";
import { fmt, fmtDate } from "@/lib/utils";
import { Heart, MessageCircle, Eye, Bookmark, Users, TrendingUp, ExternalLink, Share2 } from "lucide-react";

const GOLD = "#C9A227";
const GOLD_LIGHT = "#F5E9BE";

/* ── Date ranges ──────────────────────────────────────── */

const RANGES = [
  { key: "30", label: "30 Days" },
  { key: "90", label: "90 Days" },
  { key: "180", label: "6 Months" },
  { key: "all", label: "All Time" },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

function cutoffFor(range: RangeKey): string | null {
  if (range === "all") return null;
  const d = new Date();
  d.setDate(d.getDate() - Number(range));
  return d.toISOString().slice(0, 10);
}

/* ── KPI Card ─────────────────────────────────────────── */

function KPI({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-xs font-medium text-[#64748b]">{icon}{label}</span>
      <span className="text-2xl font-bold text-[#0f172a]">{value}</span>
      {sub && <span className="text-xs text-[#94a3b8]">{sub}</span>}
    </div>
  );
}

/* ── Section card ─────────────────────────────────────── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
      <h2 className="text-sm font-semibold text-[#0f172a] mb-4">{title}</h2>
      {children}
    </div>
  );
}

/* ── Network posts table ──────────────────────────────── */

const POSTS_PER_PAGE = 25;

function NetworkPostsTable({ posts }: { posts: NiltvNetworkPost[] }) {
  const [page, setPage] = useState(0);
  const total = posts.length;
  const totalPages = Math.ceil(total / POSTS_PER_PAGE);
  const pagePosts = posts.slice(page * POSTS_PER_PAGE, (page + 1) * POSTS_PER_PAGE);

  if (!posts.length) {
    return (
      <div className="py-12 text-center text-sm text-[#94a3b8]">
        No network posts yet. The nightly Instagram pull populates this table.
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
              <th className="py-2 pr-4 font-medium">Date</th>
              <th className="py-2 pr-4 font-medium">Account</th>
              <th className="py-2 pr-4 font-medium">Type</th>
              <th className="py-2 pr-4 font-medium text-right">Views</th>
              <th className="py-2 pr-4 font-medium text-right">Reach</th>
              <th className="py-2 pr-4 font-medium text-right">Likes</th>
              <th className="py-2 pr-4 font-medium text-right">Comments</th>
              <th className="py-2 pr-4 font-medium text-right">Shares</th>
              <th className="py-2 pr-4 font-medium text-right">Saves</th>
              <th className="py-2 font-medium w-8"></th>
            </tr>
          </thead>
          <tbody>
            {pagePosts.map((p) => (
              <tr key={p.id} className="border-b border-[#f1f5f9] hover:bg-[#fdf9ee]">
                <td className="py-2 pr-4 text-[#64748b] text-xs">{fmtDate(p.publish_time)}</td>
                <td className="py-2 pr-4 text-[#0f172a] text-xs font-medium">
                  {p.account_username ? `@${p.account_username}` : p.account_name ?? "—"}
                </td>
                <td className="py-2 pr-4">
                  {p.post_type ? (
                    <span className="inline-block text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#f1f5f9] text-[#64748b]">
                      {formatLabel(p.post_type)}
                    </span>
                  ) : "—"}
                </td>
                <td className="py-2 pr-4 text-right text-[#0f172a] font-medium">{p.views != null ? fmt(p.views) : "—"}</td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{p.reach != null ? fmt(p.reach) : (p.projected_reach != null ? <span className="text-[#94a3b8]">~{fmt(p.projected_reach)}</span> : "—")}</td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{p.likes != null ? fmt(p.likes) : "—"}</td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{p.comments != null ? fmt(p.comments) : "—"}</td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{p.shares != null ? fmt(p.shares) : "—"}</td>
                <td className="py-2 pr-4 text-right text-[#0f172a]">{p.saves != null ? fmt(p.saves) : "—"}</td>
                <td className="py-2">
                  {p.permalink && (
                    <a href={p.permalink} target="_blank" rel="noopener noreferrer" className="text-[#94a3b8] hover:text-[#C9A227]">
                      <ExternalLink size={12} />
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-[#94a3b8]">{total} posts</span>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="px-2 py-1 text-xs rounded border border-[#e2e8f0] text-[#64748b] hover:bg-[#f8fafc] disabled:opacity-30 disabled:cursor-not-allowed">Prev</button>
            <span className="text-xs text-[#64748b]">{page + 1} / {totalPages}</span>
            <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="px-2 py-1 text-xs rounded border border-[#e2e8f0] text-[#64748b] hover:bg-[#f8fafc] disabled:opacity-30 disabled:cursor-not-allowed">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Props ────────────────────────────────────────────── */

interface Props {
  profile: BrandSnapshot | null;
  networkPosts: NiltvNetworkPost[];
  networkSummary: NiltvNetworkSummary | null;
}

/* ── Main view ────────────────────────────────────────── */

export default function NiltvView({ profile, networkPosts, networkSummary }: Props) {
  const [range, setRange] = useState<RangeKey>("all");

  const cutoff = cutoffFor(range);

  const filteredNetworkPosts = useMemo(
    () => (cutoff ? networkPosts.filter((p) => (p.publish_time ?? "") >= cutoff) : networkPosts),
    [networkPosts, cutoff],
  );

  const networkKPIs = useMemo(() => {
    if (!cutoff && networkSummary) return networkSummary;
    if (!filteredNetworkPosts.length) return null;
    let views = 0, likes = 0, comments = 0, shares = 0, saves = 0, reach = 0;
    const accounts = new Set<string>();
    for (const p of filteredNetworkPosts) {
      views += p.views ?? 0;
      likes += p.likes ?? 0;
      comments += p.comments ?? 0;
      shares += p.shares ?? 0;
      saves += p.saves ?? 0;
      reach += p.reach ?? p.projected_reach ?? 0;
      if (p.account_username) accounts.add(p.account_username);
    }
    return {
      total_posts: filteredNetworkPosts.length,
      total_views: views,
      total_likes: likes,
      total_comments: comments,
      total_shares: shares,
      total_saves: saves,
      total_reach: reach,
      unique_accounts: accounts.size,
      avg_likes: filteredNetworkPosts.length ? Math.round(likes / filteredNetworkPosts.length) : 0,
    };
  }, [filteredNetworkPosts, cutoff, networkSummary]);

  const handle = profile?.username ? `@${profile.username}` : "@niltv";

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            {/* NILTV gold accent bar */}
            <div className="w-1 h-7 rounded-full" style={{ background: GOLD }} />
            <h1 className="text-xl font-bold text-[#0f172a]">NILTV</h1>
            <span className="text-xs font-medium px-2 py-0.5 rounded-full" style={{ background: GOLD_LIGHT, color: "#7a5f00" }}>
              THE HOME OF NIL CONTENT
            </span>
          </div>
          <p className="text-sm text-[#64748b] pl-4">
            Instagram analytics for{" "}
            <a
              href={`https://www.instagram.com/${profile?.username ?? "niltv"}/`}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline font-medium"
              style={{ color: GOLD }}
            >
              {handle}
            </a>
            {profile?.bio && <span className="ml-2 text-[#94a3b8]">— {profile.bio}</span>}
          </p>
        </div>

        {/* Date range pills */}
        <div className="flex gap-1 bg-[#f1f5f9] rounded-lg p-1">
          {RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className="px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
              style={
                range === r.key
                  ? { background: GOLD, color: "#fff" }
                  : { color: "#64748b" }
              }
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Network / Collab section ── */}
      <div className="flex items-center gap-3 mt-2">
        <div className="w-1 h-5 rounded-full" style={{ background: GOLD }} />
        <h2 className="text-base font-bold text-[#0f172a]">NILTV Network — Collab Posts</h2>
        <span className="text-xs text-[#94a3b8]">Affiliated creator posts via the Instagram Graph API</span>
      </div>

      {networkKPIs && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <KPI icon={<Eye size={12} />} label="Total Views" value={fmt(networkKPIs.total_views)} />
          <KPI icon={<Users size={12} />} label="Reach" value={fmt(networkKPIs.total_reach)} />
          <KPI icon={<Heart size={12} />} label="Likes" value={fmt(networkKPIs.total_likes)} />
          <KPI icon={<MessageCircle size={12} />} label="Comments" value={fmt(networkKPIs.total_comments)} />
          <KPI icon={<Share2 size={12} />} label="Shares" value={fmt(networkKPIs.total_shares)} />
          <KPI icon={<Bookmark size={12} />} label="Saves" value={fmt(networkKPIs.total_saves)} />
          <KPI icon={<TrendingUp size={12} />} label="Total Posts" value={fmt(networkKPIs.total_posts)} />
          <KPI icon={<Users size={12} />} label="Accounts" value={fmt(networkKPIs.unique_accounts)} />
        </div>
      )}

      <Section title={`Network Posts · ${filteredNetworkPosts.length} shown`}>
        <NetworkPostsTable posts={filteredNetworkPosts} />
      </Section>
    </div>
  );
}

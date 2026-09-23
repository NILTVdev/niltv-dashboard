"use client";

import { useState, useMemo } from "react";
import { fmt, fmtDate, fmtCurrency } from "@/lib/utils";
import type { ZoomphPost } from "@/lib/types";
import { ExternalLink } from "lucide-react";

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

/**
 * Extract a handle from a social media URL.
 * e.g. "https://twitter.com/DukeFootball/status/123" → "dukefootball"
 *      "https://www.instagram.com/dukembb/p/456"      → "dukembb"
 */
function handleFromUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const { hostname, pathname } = new URL(url);
    // Match twitter.com, x.com, instagram.com, facebook.com, youtube.com, tiktok.com
    if (/(?:twitter|x|instagram|facebook|tiktok)\.com$/i.test(hostname)) {
      const seg = pathname.split("/").filter(Boolean)[0]?.toLowerCase();
      // Skip non-handle path segments (e.g. /p/CODE, /reel/CODE, /stories/...)
      if (seg && !["p", "reel", "reels", "stories", "tv", "live", "status", "posts", "videos", "photo", "watch"].includes(seg)) return seg;
    }
    if (/youtube\.com$/i.test(hostname)) {
      // /channel/UC... or /@handle or /c/handle
      const parts = pathname.split("/").filter(Boolean);
      if (parts[0] === "@" || parts[0]?.startsWith("@")) return parts[0].replace("@", "").toLowerCase();
      if (parts.length >= 2 && (parts[0] === "c" || parts[0] === "channel")) return parts[1].toLowerCase();
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * Normalize display-name variants across platforms to a single canonical sport.
 * Checked after HANDLE_TO_SPORT fails, before falling back to the raw string.
 */
const DISPLAY_NAME_PATTERNS: [RegExp, string][] = [
  [/duke\s+track\s*[&+]\s*field/i, "Track & Field"],
  [/track\s*[&+]\s*field/i, "Track & Field"],
  [/cross\s*country/i, "Track & Field"],
  [/duke\s+women'?s?\s+basketball/i, "Women's Basketball"],
  [/women'?s?\s+basketball/i, "Women's Basketball"],
  [/duke\s+basketball/i, "Men's Basketball"],
  [/^basketball$/i, "Men's Basketball"],
  [/duke\s+women'?s?\s+soccer/i, "Women's Soccer"],
  [/duke\s+men'?s?\s+soccer/i, "Men's Soccer"],
  [/duke\s+women'?s?\s+lacrosse/i, "Women's Lacrosse"],
  [/duke\s+men'?s?\s+lacrosse/i, "Men's Lacrosse"],
  [/duke\s+women'?s?\s+tennis/i, "Women's Tennis"],
  [/duke\s+men'?s?\s+tennis/i, "Men's Tennis"],
  [/duke\s+women'?s?\s+golf/i, "Women's Golf"],
  [/duke\s+men'?s?\s+golf/i, "Men's Golf"],
  [/duke\s+swim/i, "Swim and Dive"],
  [/duke\s+football/i, "Football"],
  [/duke\s+softball/i, "Softball"],
  [/duke\s+baseball/i, "Baseball"],
  [/duke\s+volleyball/i, "Volleyball"],
  [/duke\s+wrestling/i, "Wrestling"],
  [/duke\s+field\s+hockey/i, "Field Hockey"],
  [/duke\s+fencing/i, "Fencing"],
  [/duke\s+rowing/i, "Rowing"],
  [/duke\s+athletics/i, "Athletics"],
];

/** Resolve a raw author string (or URL fallback) to a readable sport name. */
function resolveAccount(author: string | null, url?: string | null): string {
  // Try the author field first
  if (author) {
    const key = author.replace(/^@/, "").trim().toLowerCase();
    if (HANDLE_TO_SPORT[key]) return HANDLE_TO_SPORT[key];
    // Try display-name patterns for multi-word names that vary across platforms
    const trimmed = author.trim();
    for (const [pattern, sport] of DISPLAY_NAME_PATTERNS) {
      if (pattern.test(trimmed)) return sport;
    }
    return author;
  }
  // Fall back to extracting handle from the post URL
  const fromUrl = handleFromUrl(url ?? null);
  if (fromUrl && HANDLE_TO_SPORT[fromUrl]) return HANDLE_TO_SPORT[fromUrl];
  if (fromUrl) return fromUrl;
  return "Unknown";
}

interface Props {
  posts: ZoomphPost[];
  platforms: string[];
  hideAccountFilter?: boolean;
}

export default function ZoomphTable({ posts, platforms, hideAccountFilter }: Props) {
  const [platform, setPlatform] = useState("all");
  const [account, setAccount] = useState("all");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<"impressions" | "engagement" | "posted_at">("posted_at");

  // Build unique sorted list of resolved account names
  const accountNames = useMemo(() => {
    const names = new Set<string>();
    for (const p of posts) {
      const name = resolveAccount(p.author, p.url);
      if (name !== "Unknown") names.add(name);
    }
    return [...names].sort();
  }, [posts]);

  const filtered = useMemo(() => {
    return posts
      .filter((p) => {
        if (platform !== "all" && p.platform !== platform) return false;
        if (account !== "all" && resolveAccount(p.author, p.url) !== account) return false;
        if (search) {
          const q = search.toLowerCase();
          const sport = resolveAccount(p.author, p.url).toLowerCase();
          return (
            p.author?.toLowerCase().includes(q) ||
            sport.includes(q) ||
            p.message?.toLowerCase().includes(q) ||
            p.platform?.toLowerCase().includes(q)
          );
        }
        return true;
      })
      .sort((a, b) => {
        if (sortKey === "posted_at") {
          return (b.posted_at ?? "").localeCompare(a.posted_at ?? "");
        }
        return (b[sortKey] ?? 0) - (a[sortKey] ?? 0);
      });
  }, [posts, platform, account, search, sortKey]);

  return (
    <div className="space-y-4">
      <div className="flex gap-3 flex-wrap">
        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          className="px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
        >
          <option value="all">All Platforms</option>
          {platforms.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
{!hideAccountFilter && (
        <select
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          className="px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
        >
          <option value="all">All Accounts</option>
          {accountNames.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        )}
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as typeof sortKey)}
          className="px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
        >
          <option value="posted_at">Newest First</option>
          <option value="impressions">Highest Impressions</option>
          <option value="engagement">Highest Engagement</option>
        </select>
        <input
          type="text"
          placeholder="Search account or caption…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)] w-64"
        />
      </div>

      <div className="bg-white rounded-xl border border-[#e2e8f0] shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e2e8f0]">
              {["Date", "Platform", "Account", "Impressions", "Engagement", "Likes", "Valuation", "Link"].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 200).map((p) => (
              <tr key={p.id} className="border-b border-[#f1f5f9] last:border-0 hover:bg-[#f8fafc] transition-colors">
                <td className="px-4 py-3 whitespace-nowrap text-[#64748b]">{fmtDate(p.posted_at)}</td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <span className="text-xs bg-[var(--brand-pale)] text-[var(--brand)] font-medium px-2 py-0.5 rounded-full">
                    {p.platform ?? "—"}
                  </span>
                </td>
                <td className="px-4 py-3 whitespace-nowrap font-medium">{resolveAccount(p.author, p.url)}</td>
                <td className="px-4 py-3 whitespace-nowrap tabular-nums">{fmt(p.impressions)}</td>
                <td className="px-4 py-3 whitespace-nowrap tabular-nums">{fmt(p.engagement)}</td>
                <td className="px-4 py-3 whitespace-nowrap tabular-nums">{fmt(p.like_count)}</td>
                <td className="px-4 py-3 whitespace-nowrap tabular-nums">{fmtCurrency(p.valuation ?? p.brand_exposure_value ?? 0)}</td>
                <td className="px-4 py-3">
                  {p.url ? (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--brand)] hover:underline flex items-center gap-1"
                    >
                      <ExternalLink size={12} /> Open
                    </a>
                  ) : "—"}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-[#94a3b8]">No posts found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-[#94a3b8]">Showing {Math.min(filtered.length, 200)} of {filtered.length} posts</p>
    </div>
  );
}

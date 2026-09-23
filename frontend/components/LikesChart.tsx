"use client";
import { useBrand } from "@/components/BrandProvider";

import { useState } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { Post } from "@/lib/types";
import { fmt, fmtDate } from "@/lib/utils";

interface EngagementDay {
  date: string;
  likes: number;
  comments: number;
}

interface Props {
  posts: Post[];
  engagementByDay?: EngagementDay[];
}

type ChartMode = "cumulative" | "daily";

export default function LikesChart({ posts, engagementByDay }: Props) {
  const { brand: uiBrand } = useBrand();
  const [mode, setMode] = useState<ChartMode>("cumulative");

  // Use snapshot data if available, otherwise fall back to post data
  const hasSnapshots = engagementByDay && engagementByDay.length > 0;

  let daily: { date: string; likes: number }[];

  if (hasSnapshots) {
    // Snapshot data: actual tracked engagement over time (already sorted by date from API)
    daily = engagementByDay.map((d) => ({
      date: fmtDate(d.date),
      likes: d.likes,
    }));
  } else {
    // Fallback: derive from post data (likes by post date, not tracked over time)
    const sorted = [...posts]
      .filter((p) => p.posted_at != null && p.like_count != null)
      .sort((a, b) => (a.posted_at ?? "").localeCompare(b.posted_at ?? ""));

    const byDate = new Map<string, number>();
    for (const p of sorted) {
      const d = (p.posted_at ?? "").slice(0, 10);
      byDate.set(d, (byDate.get(d) ?? 0) + (p.like_count ?? 0));
    }
    daily = [...byDate.entries()].map(([iso, likes]) => ({
      date: fmtDate(iso),
      likes,
    }));
  }

  const cumulative = daily.reduce<{ date: string; likes: number }[]>((acc, d) => {
    const prev = acc.length ? acc[acc.length - 1].likes : 0;
    acc.push({ date: d.date, likes: prev + d.likes });
    return acc;
  }, []);

  const data = mode === "cumulative" ? cumulative : daily;

  if (daily.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet — check back after more posts.
      </div>
    );
  }

  return (
    <>
      <div className="flex gap-1 mb-3">
        <button
          onClick={() => setMode("cumulative")}
          className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
            mode === "cumulative"
              ? "bg-[var(--brand)] text-white"
              : "bg-[#f1f5f9] text-[#64748b] hover:bg-[#e2e8f0]"
          }`}
        >
          Cumulative
        </button>
        <button
          onClick={() => setMode("daily")}
          className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
            mode === "daily"
              ? "bg-[var(--brand)] text-white"
              : "bg-[#f1f5f9] text-[#64748b] hover:bg-[#e2e8f0]"
          }`}
        >
          Daily
        </button>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        {mode === "cumulative" ? (
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v) => fmt(v)}
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <Tooltip
              formatter={(v: unknown) => [fmt(v as number | undefined), "Likes"] as [string, string]}
              contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
            />
            <Line
              type="monotone"
              dataKey="likes"
              stroke={uiBrand.colors.brand}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v) => fmt(v)}
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <Tooltip
              formatter={(v: unknown) => [fmt(v as number | undefined), "Likes"] as [string, string]}
              contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
            />
            <Bar dataKey="likes" fill={uiBrand.colors.brand} radius={[4, 4, 0, 0]} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </>
  );
}

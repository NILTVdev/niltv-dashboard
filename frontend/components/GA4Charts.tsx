"use client";
import { useBrand } from "@/components/BrandProvider";

import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import type { GA4Snapshot, GA4Summary } from "@/lib/types";
import { fmt, fmtDate } from "@/lib/utils";

interface Props {
  snapshots: GA4Snapshot[];
  summary: GA4Summary;
}

export default function GA4Charts({ snapshots, summary }: Props) {
  const { brand: uiBrand } = useBrand();
  // Aggregate snapshots by date (sum across all source/medium combos)
  const byDay: Record<string, { sessions: number; users: number; pageviews: number }> = {};
  for (const s of snapshots) {
    const day = s.date.slice(0, 10);
    if (!byDay[day]) byDay[day] = { sessions: 0, users: 0, pageviews: 0 };
    byDay[day].sessions += s.sessions ?? 0;
    byDay[day].users += s.total_users ?? 0;
    byDay[day].pageviews += s.pageviews ?? 0;
  }
  const timeData = Object.entries(byDay)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, v]) => ({ date: fmtDate(date), ...v }));

  const sourceData = summary.traffic_sources.slice(0, 10).map((s) => ({
    name: `${s.source || "(unknown)"} / ${s.medium || "(unknown)"}`,
    sessions: s.sessions,
  }));

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Sessions / Users / Pageviews over time */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4">Traffic Over Time</h3>
        {timeData.length > 1 ? (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={timeData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "#94a3b8" }}
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
              <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="sessions" stroke={uiBrand.colors.brand} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="users" stroke={uiBrand.colors.brandLight} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="pageviews" stroke="#94a3b8" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : timeData.length === 1 ? (
          <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
            {timeData[0].date}: {fmt(timeData[0].sessions)} sessions, {fmt(timeData[0].users)} users, {fmt(timeData[0].pageviews)} pageviews
          </div>
        ) : (
          <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">No data yet.</div>
        )}
      </div>

      {/* Traffic Sources */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
        <h3 className="text-sm font-semibold text-[#0f172a] mb-4">Top Traffic Sources</h3>
        {sourceData.length > 0 ? (
          <ResponsiveContainer width="100%" height={Math.max(260, sourceData.length * 36)}>
            <BarChart data={sourceData} layout="vertical" margin={{ left: 120, right: 16, top: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
              <XAxis
                type="number"
                tickFormatter={(v) => fmt(v)}
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 11, fill: "#64748b" }}
                axisLine={false}
                tickLine={false}
                width={110}
                interval={0}
              />
              <Tooltip
                formatter={(v: unknown) => [fmt(v as number | undefined), "Sessions"] as [string, string]}
                contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
              />
              <Bar dataKey="sessions" fill={uiBrand.colors.brand} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">No data yet.</div>
        )}
      </div>
    </div>
  );
}

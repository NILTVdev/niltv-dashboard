"use client";
import { useBrand } from "@/components/BrandProvider";

import { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  LineChart,
  Line,
} from "recharts";
import type { ZoomphSummary, ZoomphDailyImpressions } from "@/lib/types";
import { fmt } from "@/lib/utils";

interface SummaryProps {
  summary: ZoomphSummary[];
}

export function PlatformBreakdown({ summary }: SummaryProps) {
  const { brand: uiBrand } = useBrand();
  const data = [...summary]
    .filter((s) => s.platform)
    .sort((a, b) => b.total_impressions - a.total_impressions);

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} layout="vertical" margin={{ left: 80, right: 16, top: 8, bottom: 8 }}>
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
          dataKey="platform"
          tick={{ fontSize: 11, fill: "#64748b" }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          formatter={(v: unknown) => [fmt(v as number | undefined), "Impressions"] as [string, string]}
          contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
        />
        <Bar dataKey="total_impressions" fill={uiBrand.colors.brand} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

interface TimeProps {
  data: ZoomphDailyImpressions[];
}

type ChartMode = "cumulative" | "daily";

export function ImpressionsTimeSeries({ data: raw }: TimeProps) {
  const { brand: uiBrand } = useBrand();
  const [mode, setMode] = useState<ChartMode>("cumulative");
  const sorted = [...raw].sort((a, b) => a.date.localeCompare(b.date));

  if (!sorted.length) return null;

  const cumulative = sorted.reduce<ZoomphDailyImpressions[]>((acc, d) => {
    const prev = acc.length ? acc[acc.length - 1].impressions : 0;
    acc.push({ date: d.date, impressions: prev + d.impressions });
    return acc;
  }, []);

  const data = mode === "cumulative" ? cumulative : sorted;

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
            <Tooltip
              formatter={(v: unknown) => [fmt(v as number | undefined), "Impressions"] as [string, string]}
              contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
            />
            <Line
              type="monotone"
              dataKey="impressions"
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
            <Tooltip
              formatter={(v: unknown) => [fmt(v as number | undefined), "Impressions"] as [string, string]}
              contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
            />
            <Bar dataKey="impressions" fill={uiBrand.colors.brand} radius={[4, 4, 0, 0]} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </>
  );
}

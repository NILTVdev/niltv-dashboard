"use client";
import { useBrand } from "@/components/BrandProvider";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { Snapshot } from "@/lib/types";
import { fmt, fmtDate } from "@/lib/utils";

interface Props {
  snapshots: Snapshot[];
}

export default function FollowerChart({ snapshots }: Props) {
  const { brand: uiBrand } = useBrand();
  const data = [...snapshots]
    .filter((s) => s.ig_followers != null)
    .reverse()
    .map((s) => ({
      date: fmtDate(s.pulled_at),
      followers: s.ig_followers,
    }));

  if (data.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">
        Not enough data yet — check back after the next pull.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
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
          formatter={(v: unknown) => [fmt(v as number | undefined), "Followers"] as [string, string]}
          contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
        />
        <Line
          type="monotone"
          dataKey="followers"
          stroke={uiBrand.colors.brand}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

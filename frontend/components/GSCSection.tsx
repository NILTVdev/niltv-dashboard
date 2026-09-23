"use client";
import { useBrand } from "@/components/BrandProvider";

import { useState, useMemo } from "react";
import {
  LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import type { GSCDailyTotal, GSCSummary } from "@/lib/types";
import { fmt, fmtDate } from "@/lib/utils";

interface Props {
  totals: GSCDailyTotal[];
  summary: GSCSummary;
}

type SortField = "clicks" | "impressions" | "avg_ctr" | "avg_position";
type SortDir = "asc" | "desc";

function SortHeader({
  label,
  field,
  activeField,
  dir,
  onSort,
}: {
  label: string;
  field: SortField;
  activeField: SortField | null;
  dir: SortDir;
  onSort: (f: SortField) => void;
}) {
  const active = activeField === field;
  return (
    <th
      className="px-3 py-2 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-[var(--brand)] transition-colors"
      onClick={() => onSort(field)}
    >
      {label}
      <span className="ml-1 inline-block w-3 text-[10px]">
        {active ? (dir === "desc" ? "▼" : "▲") : "⇅"}
      </span>
    </th>
  );
}

export default function GSCSection({ totals, summary }: Props) {
  const { brand: uiBrand } = useBrand();
  // Daily totals are already one row per day — no aggregation needed
  const timeData = totals
    .map((t) => ({
      date: fmtDate(t.date),
      sortKey: t.date.slice(0, 10),
      clicks: t.clicks ?? 0,
      impressions: t.impressions ?? 0,
    }))
    .sort((a, b) => a.sortKey.localeCompare(b.sortKey));

  // Sort state for queries table
  const [qSortField, setQSortField] = useState<SortField | null>(null);
  const [qSortDir, setQSortDir] = useState<SortDir>("desc");

  // Sort state for pages table
  const [pSortField, setPSortField] = useState<SortField | null>(null);
  const [pSortDir, setPSortDir] = useState<SortDir>("desc");

  function toggleSort(
    current: SortField | null,
    dir: SortDir,
    setField: (f: SortField) => void,
    setDir: (d: SortDir) => void,
    field: SortField,
  ) {
    if (current === field) {
      setDir(dir === "desc" ? "asc" : "desc");
    } else {
      setField(field);
      setDir("desc");
    }
  }

  const sortedQueries = useMemo(() => {
    if (!qSortField) return summary.top_queries;
    const sorted = [...summary.top_queries].sort((a, b) => {
      const av = a[qSortField], bv = b[qSortField];
      return qSortDir === "desc" ? bv - av : av - bv;
    });
    return sorted;
  }, [summary.top_queries, qSortField, qSortDir]);

  const sortedPages = useMemo(() => {
    if (!pSortField) return summary.top_pages;
    const sorted = [...summary.top_pages].sort((a, b) => {
      const av = a[pSortField], bv = b[pSortField];
      return pSortDir === "desc" ? bv - av : av - bv;
    });
    return sorted;
  }, [summary.top_pages, pSortField, pSortDir]);

  return (
    <div className="space-y-4">
      {/* Clicks & Impressions over time — full width */}
      {timeData.length > 1 && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
          <h3 className="text-sm font-semibold text-[#0f172a] mb-4">Clicks & Impressions Over Time</h3>
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
              <Line type="monotone" dataKey="clicks" stroke={uiBrand.colors.brand} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="impressions" stroke="#94a3b8" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Top Queries table */}
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
          <h3 className="text-sm font-semibold text-[#0f172a] mb-4">Top Search Queries</h3>
          {sortedQueries.length > 0 ? (
            <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white">
                  <tr className="border-b border-[#e2e8f0]">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap">
                      Query
                    </th>
                    <SortHeader label="Clicks" field="clicks" activeField={qSortField} dir={qSortDir} onSort={(f) => toggleSort(qSortField, qSortDir, setQSortField, setQSortDir, f)} />
                    <SortHeader label="Impr." field="impressions" activeField={qSortField} dir={qSortDir} onSort={(f) => toggleSort(qSortField, qSortDir, setQSortField, setQSortDir, f)} />
                    <SortHeader label="CTR" field="avg_ctr" activeField={qSortField} dir={qSortDir} onSort={(f) => toggleSort(qSortField, qSortDir, setQSortField, setQSortDir, f)} />
                    <SortHeader label="Pos." field="avg_position" activeField={qSortField} dir={qSortDir} onSort={(f) => toggleSort(qSortField, qSortDir, setQSortField, setQSortDir, f)} />
                  </tr>
                </thead>
                <tbody>
                  {sortedQueries.map((q) => (
                    <tr key={q.query} className="border-b border-[#f1f5f9] last:border-0 hover:bg-[#f8fafc] transition-colors">
                      <td className="px-3 py-2 font-medium text-[#0f172a] max-w-[200px] truncate">{q.query}</td>
                      <td className="px-3 py-2 tabular-nums">{fmt(q.clicks)}</td>
                      <td className="px-3 py-2 tabular-nums">{fmt(q.impressions)}</td>
                      <td className="px-3 py-2 tabular-nums">{(q.avg_ctr * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2 tabular-nums">{q.avg_position.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">No data yet.</div>
          )}
        </div>

        {/* Top Pages table */}
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5">
          <h3 className="text-sm font-semibold text-[#0f172a] mb-4">Top Performing Pages</h3>
          {sortedPages.length > 0 ? (
            <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white">
                  <tr className="border-b border-[#e2e8f0]">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap">
                      Page
                    </th>
                    <SortHeader label="Clicks" field="clicks" activeField={pSortField} dir={pSortDir} onSort={(f) => toggleSort(pSortField, pSortDir, setPSortField, setPSortDir, f)} />
                    <SortHeader label="Impr." field="impressions" activeField={pSortField} dir={pSortDir} onSort={(f) => toggleSort(pSortField, pSortDir, setPSortField, setPSortDir, f)} />
                    <SortHeader label="CTR" field="avg_ctr" activeField={pSortField} dir={pSortDir} onSort={(f) => toggleSort(pSortField, pSortDir, setPSortField, setPSortDir, f)} />
                    <SortHeader label="Pos." field="avg_position" activeField={pSortField} dir={pSortDir} onSort={(f) => toggleSort(pSortField, pSortDir, setPSortField, setPSortDir, f)} />
                  </tr>
                </thead>
                <tbody>
                  {sortedPages.map((p) => {
                    // Show just the path, not the full URL
                    let displayPage = p.page;
                    try {
                      displayPage = new URL(p.page).pathname;
                    } catch { /* keep original if not a valid URL */ }
                    return (
                      <tr key={p.page} className="border-b border-[#f1f5f9] last:border-0 hover:bg-[#f8fafc] transition-colors">
                        <td className="px-3 py-2 font-medium text-[#0f172a] max-w-[200px] truncate" title={p.page}>
                          {displayPage}
                        </td>
                        <td className="px-3 py-2 tabular-nums">{fmt(p.clicks)}</td>
                        <td className="px-3 py-2 tabular-nums">{fmt(p.impressions)}</td>
                        <td className="px-3 py-2 tabular-nums">{(p.avg_ctr * 100).toFixed(1)}%</td>
                        <td className="px-3 py-2 tabular-nums">{p.avg_position.toFixed(1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8]">No data yet.</div>
          )}
        </div>
      </div>
    </div>
  );
}

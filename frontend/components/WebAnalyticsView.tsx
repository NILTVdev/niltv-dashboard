"use client";

import { useState, useMemo } from "react";
import type {
  GA4Snapshot, GSCDailyTotal, GSCQuerySnapshot, GSCPageSnapshot,
} from "@/lib/types";
import {
  RANGES, type RangeKey,
  filterByRange, computeGA4Summary, computeGSCSummary,
} from "@/lib/analytics";
import WebAnalyticsKPIs from "./WebAnalyticsKPIs";
import GA4Charts from "./GA4Charts";
import GSCSection from "./GSCSection";

interface Props {
  ga4Snapshots: GA4Snapshot[];
  gscTotals: GSCDailyTotal[];
  gscQueries: GSCQuerySnapshot[];
  gscPages: GSCPageSnapshot[];
  title?: string;
  subtitle?: string;
}

export default function WebAnalyticsView({
  ga4Snapshots,
  gscTotals,
  gscQueries,
  gscPages,
  title = "Web Analytics",
  subtitle = "Site performance across Google Analytics and Search Console.",
}: Props) {
  const [range, setRange] = useState<RangeKey>("7");

  const filteredGA4 = useMemo(() => filterByRange(ga4Snapshots, range), [ga4Snapshots, range]);
  const filteredTotals = useMemo(() => filterByRange(gscTotals, range), [gscTotals, range]);
  const filteredQueries = useMemo(() => filterByRange(gscQueries, range), [gscQueries, range]);
  const filteredPages = useMemo(() => filterByRange(gscPages, range), [gscPages, range]);
  const ga4Summary = useMemo(() => computeGA4Summary(filteredGA4), [filteredGA4]);
  const gscSummary = useMemo(() => computeGSCSummary(filteredTotals, filteredQueries, filteredPages), [filteredTotals, filteredQueries, filteredPages]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a] mb-1">{title}</h1>
          <p className="text-sm text-[#64748b]">{subtitle}</p>
        </div>
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

      <WebAnalyticsKPIs ga4={ga4Summary} gsc={gscSummary} />

      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-[#0f172a]">Search Console</h2>
        <GSCSection totals={filteredTotals} summary={gscSummary} />
      </div>

      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-[#0f172a]">Google Analytics</h2>
        <GA4Charts snapshots={filteredGA4} summary={ga4Summary} />
      </div>
    </div>
  );
}

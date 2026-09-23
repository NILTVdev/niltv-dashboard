import type { ZoomphSummary } from "@/lib/types";
import { fmt, fmtCurrency } from "@/lib/utils";
import { Eye, ThumbsUp, DollarSign, LayoutGrid } from "lucide-react";

interface Props {
  summary: ZoomphSummary[];
}

export default function ZoomphKPIs({ summary }: Props) {
  const totals = summary.reduce(
    (acc, s) => ({
      posts: acc.posts + s.post_count,
      impressions: acc.impressions + s.total_impressions,
      engagement: acc.engagement + s.total_engagement,
      bev: acc.bev + s.total_bev,
    }),
    { posts: 0, impressions: 0, engagement: 0, bev: 0 }
  );

  const er =
    totals.impressions > 0
      ? ((totals.engagement / totals.impressions) * 100).toFixed(2) + "%"
      : "—";

  const cards = [
    { label: "Posts", value: fmt(totals.posts), icon: LayoutGrid },
    { label: "Total Impressions", value: fmt(totals.impressions), icon: Eye },
    { label: "Total Engagement", value: fmt(totals.engagement), icon: ThumbsUp },
    { label: "Engagement Rate", value: er, icon: ThumbsUp },
    { label: "Social Valuation", value: fmtCurrency(totals.bev), icon: DollarSign },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="bg-white rounded-xl border border-[#e2e8f0] shadow-sm p-4"
        >
          <div className="flex items-center gap-2 text-[#64748b] mb-2">
            <c.icon size={14} />
            <p className="text-xs">{c.label}</p>
          </div>
          <p className="text-2xl font-bold text-[var(--brand)]">{c.value}</p>
        </div>
      ))}
    </div>
  );
}
